import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.llm.gemini_client import GeminiClient

SEED_DIR = ROOT / "data" / "seed"
RAW_DIR = ROOT / "data" / "raw"

DOMAINS = ["phones", "movies", "books", "laptops", "cars", "bikes", "courses"]

def get_schema_example(domain: str) -> str:
    with open(SEED_DIR / f"{domain}.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        if "data" in data:
            item = data["data"][0]
        elif "laptops" in data:
            item = data["laptops"][0]
        elif "vehicles" in data:
            item = data["vehicles"][0]
        elif "movies" in data:
            item = data["movies"][0]
        elif "records" in data:
            item = data["records"][0]
        elif "bikes" in data:
            item = data["bikes"][0]
        else:
            item = next(iter(data.values()))[0]
    else:
        item = data[0]
    
    return json.dumps(item, indent=2)

def get_array_key(domain: str) -> str:
    if domain == "phones": return "data"
    if domain == "movies": return "movies"
    if domain == "books": return "records"
    if domain == "laptops": return "laptops"
    if domain == "cars": return "vehicles"
    if domain == "bikes": return "bikes"
    return ""

async def generate_batch(client: GeminiClient, domain: str, batch_idx: int) -> list[dict]:
    schema = get_schema_example(domain)
    prompt = f"""You are a data generation API. Generate a JSON array containing 25 REAL, well-known {domain}. 
DO NOT INCLUDE FAKE OR SYNTHETIC ITEMS. Use your knowledge to find real-world {domain} (e.g. real movies, real smartphone models like iPhone 15, real books, etc).
Fill out ALL fields accurately based on real specs. 
If a subjective field like 'mood', 'blurb', or 'highlights' is required, impute it accurately.
Ensure variety (e.g., different brands, genres, or manufacturers).
CRITICAL: The output MUST be a valid JSON array of objects that exactly matches this schema format (do not include the outer object, just the array of items):
{schema}

Output ONLY valid JSON. No markdown formatting, no backticks, no explanations. Just the [ ... ].
"""
    try:
        response = await client._generate(system_prompt="You return only JSON.", user_prompt=prompt, json_mode=True, model=None)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        
        items = json.loads(response.strip())
        if not isinstance(items, list):
            items = [items]
        for item in items:
            item["synthetic"] = False
        print(f"[{domain}] Batch {batch_idx} generated {len(items)} items")
        return items
    except Exception as e:
        print(f"[{domain}] Batch {batch_idx} failed: {e}")
        return []

async def process_domain(client: GeminiClient, domain: str):
    print(f"Starting domain: {domain}")
    # 8 batches of 25 = 200 real items per domain
    tasks = [generate_batch(client, domain, i) for i in range(8)]
    results = await asyncio.gather(*tasks)
    
    real_items = []
    for batch in results:
        real_items.extend(batch)
        
    with open(SEED_DIR / f"{domain}.json", "r", encoding="utf-8") as f:
        seed_data = json.load(f)
        
    array_key = get_array_key(domain)
    if array_key:
        seed_items = seed_data[array_key]
        seed_items.extend(real_items)
        seed_data[array_key] = seed_items
        final_data = seed_data
    else:
        seed_data.extend(real_items)
        final_data = seed_data
        
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_DIR / f"{domain}.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)
        
    print(f"Finished {domain}: {len(real_items)} real items generated.")

async def main():
    client = GeminiClient()
    # Process domains sequentially to avoid overwhelming even the pooled keys
    for domain in DOMAINS:
        await process_domain(client, domain)
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
