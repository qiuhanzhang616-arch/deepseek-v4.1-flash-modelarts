"""Synthetic inventory repository context; contains no customer source code."""
import hashlib
from functools import lru_cache
import os

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
DEFECT_FUNCTION = "reserve_stock_0000"


@lru_cache(maxsize=32)
def repository(group):
    seed = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16)
    parts = ["# Inventory service repository snapshot\n"
             "Contract: reservation quantity must be a positive integer. A rejected\n"
             "reservation must leave stock unchanged; insufficient stock raises ValueError.\n"
             "Each tenant adapter implements this same contract.\n\n"
             "## src/inventory_0000.py\n"
             "def reserve_stock_0000(stock, sku, quantity):\n"
             "    available = stock.get(sku, 0)\n"
             "    if available < quantity:\n"
             "        raise ValueError('insufficient stock')\n"
             "    stock[sku] = available - quantity\n"
             "    return {'sku': sku, 'reserved': quantity, 'remaining': stock[sku]}\n\n"
             "## tests/test_inventory_0000.py\n"
             "def test_positive_reservation():\n"
             "    stock = {'SKU-BASE': 7}\n"
             "    result = reserve_stock_0000(stock, 'SKU-BASE', 3)\n"
             "    assert result['remaining'] == 4\n"
             "    assert stock['SKU-BASE'] == 4\n\n"]
    for i in range(1, 1801):
        capacity = 100 + (seed + i * 37) % 9000
        quantity = 1 + (seed + i * 11) % 31
        parts.append(f"""## src/tenant_{i:04d}/inventory.py
TENANT_ID = "tenant-{i:04d}"
SKU = "SKU-{seed % 997:03d}-{i:04d}"
CAPACITY = {capacity}

def reserve_stock_{i:04d}(stock, sku, quantity):
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    available = stock.get(sku, 0)
    if available < quantity:
        raise ValueError("insufficient stock")
    stock[sku] = available - quantity
    return dict(tenant=TENANT_ID, sku=sku, reserved=quantity, remaining=stock[sku])

## tests/tenant_{i:04d}/test_inventory.py
def test_reservation_{i:04d}():
    stock = {{SKU: {capacity}}}
    result = reserve_stock_{i:04d}(stock, SKU, {quantity})
    assert result["remaining"] == {capacity - quantity}
    assert result["reserved"] == {quantity}

def test_rejection_{i:04d}():
    stock = {{SKU: {capacity}}}
    before = stock.copy()
    try:
        reserve_stock_{i:04d}(stock, SKU, -{quantity})
    except ValueError:
        pass
    else:
        raise AssertionError("negative reservation accepted")
    assert stock == before

""")
    return "".join(parts)


@lru_cache(maxsize=1)
def tokenizer():
    from tokenizers import Tokenizer
    return Tokenizer.from_file(os.environ.get("PD_TOKENIZER_JSON", "/model/w4a8/model-view/tokenizer.json"))


@lru_cache(maxsize=32)
def repository_tokens(group):
    return tokenizer().encode(repository(group), add_special_tokens=False).ids


def prepare_repository(item, namespace, tokenize_url, post, model):
    import json
    group = item["prefix_group"] if item["cache_class"] == "hot" else item["request_id"]
    marker = "PD_REVIEW_" + hashlib.sha256(group.encode()).hexdigest()[:12]
    prefix = f"Review workspace {namespace}/{group}. Review ID: {marker}.\n"
    tail = ("\n[End of supplied repository excerpt; final file may be truncated.]\n"
            "Review reserve_stock_0000 against the documented reservation contract. "
            "Begin your answer with the review ID, then identify the concrete defect, "
            "explain a failing input and its effect on stock, and propose a minimal patch "
            "and regression tests. Cite the function name and quantity validation. "
            "Use the other tenant adapters as implementation context.")
    target = item["input_tokens"]
    tokens = repository_tokens(group)
    budget = target - 200
    for _ in range(12):
        if not 0 < budget <= len(tokens):
            raise ValueError("repository token budget outside generated corpus")
        body = tokenizer().decode(tokens[:budget], skip_special_tokens=False)
        messages = [{"role": "user", "content": prefix + body + tail}]
        payload = {"model": model, "messages": messages, "add_generation_prompt": True,
                   "return_token_strs": False, "chat_template_kwargs": {"reasoning_effort": "low"}}
        with post(tokenize_url, payload, 120) as response:
            count = json.load(response)["count"]
        if count == target:
            return messages, marker
        budget += target - count
    raise ValueError(f"repository exact token construction failed: {count}/{target}")


def review_quality(body):
    lowered = body.lower()
    return DEFECT_FUNCTION in body and "quantity" in lowered and any(
        term in lowered for term in ("negative", "positive", "<= 0", "<=0"))
