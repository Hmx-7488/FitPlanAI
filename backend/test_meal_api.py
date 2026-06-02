"""餐食 API 测试脚本"""
import asyncio
import aiohttp
import json

BASE_URL = "http://localhost:8000"

async def test_meal_recognize():
    """测试食材识别接口"""
    async with aiohttp.ClientSession() as session:
        # 假设有一张测试图片
        data = aiohttp.FormData()
        data.add_field('user_id', '1')
        # data.add_field('image', open('test.jpg', 'rb'), filename='test.jpg', content_type='image/jpeg')
        
        print("测试食材识别接口...")
        print("注意：需要准备一张测试图片并取消注释上面的代码")
        print(f"POST {BASE_URL}/api/meal/recognize")
        print("预期响应：{{'recognition_id': '...', 'ingredients': [...]}}")
        print()

async def test_meal_calculate():
    """测试营养计算接口"""
    async with aiohttp.ClientSession() as session:
        test_data = {
            "recognition_id": "test_recognition_id",
            "ingredients": [
                {"name": "egg", "display_name": "鸡蛋", "estimated_weight_g": 100, "confidence": 0.9},
                {"name": "tomato", "display_name": "番茄", "estimated_weight_g": 150, "confidence": 0.85}
            ],
            "meal_type": "lunch"
        }
        
        print("测试营养计算接口...")
        print(f"POST {BASE_URL}/api/meal/calculate")
        print(f"请求数据：{json.dumps(test_data, ensure_ascii=False, indent=2)}")
        print("预期响应：{{'meal_type': 'lunch', 'items': [...], 'meal_total': {{...}}, 'daily_summary': {{...}}}}")
        print()

async def main():
    print("=== 餐食 API 测试 ===\n")
    await test_meal_recognize()
    await test_meal_calculate()
    print("测试完成！")
    print("\n启动后端服务器：")
    print("cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
    print("\n然后使用 Postman 或 curl 测试上述接口")

if __name__ == "__main__":
    asyncio.run(main())