import os
import sys
import base64
import yaml
import mimetypes
import logging
import time
import requests
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from zai import ZhipuAiClient

# 导入 Markdown 转 DOCX 功能
sys.path.append(os.path.dirname(__file__))
try:
    from md_to_docx import md_to_docx
except ImportError:
    logging.warning("md_to_docx 模块导入失败，将只生成 Markdown 文件")
    md_to_docx = None

CONFIG_FILE = "config.yaml"
LOG_FILE = "ocr_trans/ocr_process.log"
MAX_PAGES_PER_REQ = 100
OUTPUT_DIR = "ocr_trans/output"
MERGED_OUTPUT = "final_output.md"
PRICE_PER_MILLION_TOKENS = 0.2

def setup_logging():
    logger = logging.getLogger("GLM_OCR_Batch")
    logger.setLevel(logging.DEBUG)
    
    if logger.handlers:
        logger.handlers.clear()
    
    os.makedirs("ocr_trans", exist_ok=True)
    
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

def load_config(api_key_from_arg=None):
    if api_key_from_arg:
        return api_key_from_arg
    
    config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE) if '__file__' in globals() else CONFIG_FILE
    if not os.path.exists(config_path):
        raise ValueError(f"配置文件 {CONFIG_FILE} 不存在")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    maas_config = config.get('pipeline', {}).get('maas', {})
    if not maas_config.get('enabled'):
        raise ValueError("config.yaml 中 maas.enabled 必须为 true")
    
    api_key = maas_config.get('api_key')
    if not api_key:
        raise ValueError("请在 config.yaml 中填入有效的 api_key")
    
    return api_key

def check_balance(api_key):
    logger.info("正在查询账户余额...")
    url = "https://open.bigmodel.cn/api/paas/v4/usage"
    headers = {
        "Authorization": api_key
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'balance' in data['data']:
                balance = data['data']['balance']
                logger.info(f"✅ 账户余额: {balance} 元")
                return float(balance)
            else:
                logger.warning(f"无法解析余额响应: {data}")
                return None
        else:
            logger.error(f"查询余额失败: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"查询余额时发生错误: {e}")
        return None

def estimate_cost(total_pages, pages_per_split=MAX_PAGES_PER_REQ):
    num_splits = (total_pages + pages_per_split - 1) // pages_per_split
    avg_tokens_per_page = 5000
    total_tokens = num_splits * avg_tokens_per_page * pages_per_split
    cost = (total_tokens / 1_000_000) * PRICE_PER_MILLION_TOKENS
    return num_splits, cost

def split_pdf(input_pdf_path, pages_per_split=MAX_PAGES_PER_REQ):
    logger.info(f"正在分析 PDF: {input_pdf_path}")
    reader = PdfReader(input_pdf_path)
    total_pages = len(reader.pages)
    logger.info(f"PDF 总页数: {total_pages}")
    
    splits = []
    for i in range(0, total_pages, pages_per_split):
        end = min(i + pages_per_split, total_pages)
        splits.append((i, end))
    
    logger.info(f"将 PDF 分为 {len(splits)} 个部分进行处理")
    return splits

def create_pdf_split(input_pdf_path, start_page, end_page, output_path):
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    
    for page_num in range(start_page, end_page):
        writer.add_page(reader.pages[page_num])
    
    with open(output_path, 'wb') as f:
        writer.write(f)

def file_to_data_uri(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        mime_type = "application/pdf"

    with open(file_path, "rb") as file:
        file_bytes = file.read()

    base64_str = base64.b64encode(file_bytes).decode('utf-8')
    data_uri = f"data:{mime_type};base64,{base64_str}"
    return data_uri

def ocr_single_pdf(client, data_uri):
    try:
        response = client.layout_parsing.create(
            model="glm-ocr",
            file=data_uri
        )
        
        result_text = ""
        if hasattr(response, 'data') and response.data:
            if isinstance(response.data, dict):
                result_text = response.data.get('markdown', str(response.data))
            else:
                result_text = str(response.data)
        else:
            result_text = str(response)
        
        return result_text
        
    except Exception as e:
        error_msg = str(e)
        if "402" in error_msg or "403" in error_msg or "Payment Required" in error_msg or "Forbidden" in error_msg or "insufficient" in error_msg.lower() or "余额" in error_msg:
            raise RuntimeError("TOKEN_EXHAUSTED: 账户余额不足，请充值后重试")
        raise

def process_pdf(input_file_path, pages_per_split=MAX_PAGES_PER_REQ):
    logger.info("=" * 50)
    logger.info(f"开始处理文件: {input_file_path}")
    logger.info("=" * 50)
    
    api_key = load_config()
    
    balance = check_balance(api_key)
    if balance is not None and balance <= 0:
        logger.error("❌ 账户余额不足，请充值后重试!")
        return None, []
    
    reader = PdfReader(input_file_path)
    total_pages = len(reader.pages)
    num_splits, estimated_cost = estimate_cost(total_pages, pages_per_split)
    
    logger.info(f"PDF 总页数: {total_pages}")
    logger.info(f"需要处理 {num_splits} 个部分")
    logger.info(f"预估费用: 约 {estimated_cost:.2f} 元")
    
    if balance is not None and balance < estimated_cost:
        logger.warning(f"⚠️ 警告: 账户余额 ({balance:.2f} 元) 低于预估费用 ({estimated_cost:.2f} 元)")
        logger.warning("继续处理可能会导致余额不足中断，是否继续? (请手动确认)")
    
    client = ZhipuAiClient(api_key=api_key)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    splits = split_pdf(input_file_path, pages_per_split)
    all_results = []
    output_files = []
    
    base_name = Path(input_file_path).stem
    
    for idx, (start, end) in enumerate(splits):
        logger.info("-" * 40)
        logger.info(f"正在处理第 {idx + 1}/{len(splits)} 部分 (页码 {start + 1} - {end})")
        logger.info("-" * 40)
        
        split_file = os.path.join(OUTPUT_DIR, f"{base_name}_part{idx + 1}.pdf")
        
        logger.info(f"正在切分 PDF...")
        create_pdf_split(input_file_path, start, end, split_file)
        
        logger.info(f"正在转换文件为 Data URI...")
        data_uri = file_to_data_uri(split_file)
        
        logger.info(f"正在调用 GLM-OCR API (这部分可能需要一些时间)...")
        start_time = time.time()
        
        try:
            result = ocr_single_pdf(client, data_uri)
            elapsed = time.time() - start_time
            logger.info(f"✅ 第 {idx + 1} 部分处理完成! 耗时: {elapsed:.2f}秒")
            
            result_file = os.path.join(OUTPUT_DIR, f"{base_name}_part{idx + 1}.md")
            with open(result_file, 'w', encoding='utf-8') as f:
                f.write(result)
            
            output_files.append(result_file)
            all_results.append(result)
            
            logger.info(f"📄 结果已保存至: {result_file}")
            
        except Exception as e:
            error_msg = str(e)
            if "TOKEN_EXHAUSTED" in error_msg or "余额" in error_msg:
                logger.error(f"❌ 余额不足！已停止处理")
                logger.error(f"已完成 {idx} 个部分，已保存的结果将保留")
                break
            else:
                logger.error(f"❌ 第 {idx + 1} 部分处理失败: {e}")
                continue
        
        finally:
            if os.path.exists(split_file):
                os.remove(split_file)
    
    if all_results:
        logger.info("=" * 50)
        logger.info("正在合并所有结果...")
        
        merged_file = os.path.join(OUTPUT_DIR, MERGED_OUTPUT)
        with open(merged_file, 'w', encoding='utf-8') as f:
            for idx, result in enumerate(all_results):
                f.write(f"\n\n--- 第 {idx + 1} 部分 ---\n\n")
                f.write(result)
        
        # 自动转换为 DOCX 格式
        docx_file = None
        if md_to_docx:
            try:
                logger.info("正在转换为 DOCX 格式...")
                docx_file = md_to_docx(merged_file)
                logger.info(f"✅ DOCX 转换完成! 保存至: {docx_file}")
            except Exception as e:
                logger.error(f"❌ DOCX 转换失败: {e}")
        
        logger.info(f"✅ 全部完成! 合并结果已保存至: {merged_file}")
        if docx_file:
            logger.info(f"✅ DOCX 格式已生成: {docx_file}")
        logger.info(f"📁 所有输出文件位于: {os.path.abspath(OUTPUT_DIR)}")
        
        return merged_file, output_files
    else:
        logger.error("❌ 未能成功处理任何部分")
        return None, []

def main():
    if len(sys.argv) < 2:
        print("用法: python ocr_core.py <pdf文件路径> [每部分页数] [api_key]")
        print("示例: python ocr_core.py document.pdf 100")
        sys.exit(1)
    
    target_file = sys.argv[1]
    
    if not os.path.exists(target_file):
        logger.error(f"文件不存在: {target_file}")
        sys.exit(1)
    
    pages_per_split = MAX_PAGES_PER_REQ
    if len(sys.argv) >= 3:
        try:
            pages_per_split = int(sys.argv[2])
        except ValueError:
            logger.warning(f"无效的页数参数，使用默认值: {MAX_PAGES_PER_REQ}")
    
    api_key = None
    if len(sys.argv) >= 4:
        api_key = sys.argv[3]
    
    try:
        api_key = load_config(api_key_from_arg=api_key)
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        sys.exit(1)
    
    merged_file, output_files = process_pdf(target_file, pages_per_split)
    
    if merged_file:
        print("\n" + "=" * 50)
        print("处理完成!")
        print(f"主输出文件: {merged_file}")
        print(f"分部分文件: {output_files}")
        print("=" * 50)

if __name__ == "__main__":
    main()
