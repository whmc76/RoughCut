BENCHMARK_SAMPLES = [
    {
        "source_name": "20260301-171443.mp4",
        "expected_product_family": "bag",
        "expected_keywords": ["双肩包", "机能包", "联名"],
    },
    {
        "source_name": "20260209-124735.mp4",
        "expected_product_family": "flashlight",
        "expected_keywords": ["OLIGHT", "手电"],
    },
    {
        "source_name": "20260211-123939.mp4",
        "expected_product_family": "knife",
        "expected_keywords": ["刀", "折刀", "美工刀"],
    },
    {
        "source_name": "20260212-141536.mp4",
        "expected_product_family": "knife_tool",
        "expected_keywords": ["刀", "工具", "挂扣"],
    },
    {
        "source_name": "20260211-120605.mp4",
        "expected_product_family": "case",
        "expected_keywords": ["盒", "收纳", "防水盒"],
    },
    {
        "source_name": "20260213-133009.mp4",
        "expected_product_family": "accessory_material",
        "expected_keywords": ["材料", "配件", "纤维"],
    },
]

BENCHMARK_REPORT_CONTRACT_FIELDS = (
    "observed_entities",
    "resolved_entities",
    "conflicts",
    "capability_matrix",
)
