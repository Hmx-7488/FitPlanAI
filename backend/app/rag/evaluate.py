"""RAG evaluation suite - fixed test queries for offline evaluation."""
from app.rag.models import SearchQuery, GoalType, KnowledgeCategory
from app.rag.retriever import get_retriever

_EVAL_CASES = [
    {
        "id": "fat_loss_calorie",
        "query": "减脂期每天应该摄入多少热量",
        "expected_categories": ["fat_loss_standards"],
        "must_not_be_empty": True,
        "description": "Should retrieve fat loss calorie deficit guidelines",
    },
    {
        "id": "muscle_gain_surplus",
        "query": "增肌期热量盈余多少合适",
        "expected_categories": ["muscle_gain_standards"],
        "goal_type": "muscle_gain",
        "must_not_be_empty": True,
    },
    {
        "id": "chinese_meal_substitution",
        "query": "减脂期外卖怎么点餐",
        "expected_categories": ["chinese_meals"],
        "must_not_be_empty": True,
    },
    {
        "id": "beginner_training",
        "query": "新手每周训练几天合适",
        "expected_categories": ["training_principles"],
        "must_not_be_empty": True,
    },
    {
        "id": "knee_injury_limit",
        "query": "膝盖受伤后可以做什么运动",
        "expected_categories": ["risk_rules"],
        "injuries": ["knee"],
        "must_not_be_empty": True,
    },
    {
        "id": "exercise_risk",
        "query": "深蹲膝盖内扣怎么纠正",
        "expected_categories": ["exercise_technique"],
        "must_not_be_empty": True,
    },
    {
        "id": "insufficient_evidence",
        "query": "量子力学对减脂的影响",
        "max_score_threshold": 0.65,
        "description": "Should return low-confidence results for nonsensical query",
    },
    {
        "id": "wrong_premise",
        "query": "每天只吃500大卡能快速减脂吗",
        "expected_categories": ["risk_rules", "fat_loss_standards"],
        "must_not_be_empty": True,
        "description": "Should retrieve risk rules about extreme calorie restriction",
    },
    {
        "id": "protein_intake",
        "query": "减脂期每公斤体重需要多少蛋白质",
        "expected_categories": ["fat_loss_standards"],
        "must_not_be_empty": True,
    },
    {
        "id": "back_injury_deadlift",
        "query": "腰椎间盘突出能做硬拉吗",
        "expected_categories": ["risk_rules", "exercise_technique"],
        "injuries": ["back"],
        "must_not_be_empty": True,
    },
]


def run_evaluation() -> dict:
    """Run all evaluation cases and return results."""
    retriever = get_retriever()
    results = []
    pass_count = 0

    for case in _EVAL_CASES:
        gt = case.get("goal_type")
        goal = GoalType(gt) if gt else None
        sq = SearchQuery(
            query=case["query"],
            goal_type=goal,
            injuries=case.get("injuries", []),
            top_k=5,
        )
        sr = retriever.search(sq)

        # 收集命中的分类
        hit_cats = {d.category for d in sr.documents if d.category}
        hit_chunk_ids = [d.chunk_id for d in sr.documents]

        passed = True
        reason = ""

        # 1. 非空检查
        if case.get("must_not_be_empty") and sr.insufficient_evidence:
            passed = False
            reason = "Expected results but got insufficient_evidence"

        # 2. 证据不足检查
        if case.get("must_be_empty_or_insufficient") and not sr.insufficient_evidence:
            passed = False
            reason = "Expected insufficient_evidence but got results"

        # 3. 分数阈值检查
        max_thr = case.get("max_score_threshold")
        if max_thr is not None and sr.documents and sr.documents[0].score > max_thr:
            passed = False
            reason = f"Top score {sr.documents[0].score:.3f} exceeds threshold {max_thr}"

        # 4. 期望分类校验 — 至少命中一个期望分类
        expected = case.get("expected_categories", [])
        if expected and passed:
            if not hit_cats.intersection(expected):
                passed = False
                reason = f"Expected categories {expected} but got {hit_cats}"

        if passed:
            pass_count += 1
        results.append({
            "id": case["id"],
            "query": case["query"],
            "passed": passed,
            "reason": reason,
            "top_results": [
                {"title": d.title[:50], "score": d.score, "method": d.retrieval_method, "category": d.category}
                for d in sr.documents[:3]
            ],
            "hit_categories": sorted(hit_cats),
            "insufficient_evidence": sr.insufficient_evidence,
            "hit_chunk_ids": hit_chunk_ids,
        })

    total = len(_EVAL_CASES)
    return {
        "total": total,
        "passed": pass_count,
        "failed": total - pass_count,
        "pass_rate": round(pass_count / total * 100, 1) if total else 0,
        "results": results,
    }

