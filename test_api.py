#!/usr/bin/env python
"""
Test script - Webhook API ni test qilish
Usage: python test_api.py
"""
import requests
import json
from datetime import datetime

# Configuration
WEBHOOK_URL = "http://localhost:8000/webhook/api/"


def test_new_order():
    """Yangi buyurtma yuborish testi"""
    print("\n" + "=" * 50)
    print("🧪 TEST: Yangi buyurtma (order.created)")
    print("=" * 50)

    order_data = {
        "event": "order.created",
        "order": {
            "id": f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "seller_id": "seller_1",  # Bu api_identifier ga mos kelishi kerak
            "status": "new",
            "customer": {
                "name": "Alisher Navoiy",
                "phone": "+998901234567",
                "address": "Toshkent, Navoiy ko'chasi, 15-uy"
            },
            "total": 350000,
            "items": [
                {"name": "iPhone 15 Pro", "price": 300000, "quantity": 1},
                {"name": "AirPods Pro", "price": 50000, "quantity": 1}
            ],
            "notes": "Iltimos, soat 14:00 da yetkazib bering",
            "created_at": datetime.now().isoformat()
        }
    }

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=order_data,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        print(f"📤 Yuborildi: {order_data['order']['id']}")
        print(f"📥 Status: {response.status_code}")
        print(f"📄 Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

        return response.status_code == 200

    except requests.ConnectionError:
        print("❌ Server ishlamayapti. Avval 'python manage.py runserver' ni ishga tushiring")
        return False
    except Exception as e:
        print(f"❌ Xatolik: {e}")
        return False


def test_order_update():
    """Buyurtma yangilash testi"""
    print("\n" + "=" * 50)
    print("🧪 TEST: Buyurtma yangilash (order.updated)")
    print("=" * 50)

    update_data = {
        "event": "order.updated",
        "order": {
            "id": "test_order_001",  # Mavjud buyurtma ID
            "status": "processing",
            "customer": {
                "name": "Alisher Navoiy",
                "phone": "+998901234567"
            },
            "total": 350000,
            "items": []
        }
    }

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=update_data,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        print(f"📤 Yuborildi: status -> {update_data['order']['status']}")
        print(f"📥 Status: {response.status_code}")
        print(f"📄 Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

        return response.status_code == 200

    except Exception as e:
        print(f"❌ Xatolik: {e}")
        return False


def test_health_check():
    """Health check testi"""
    print("\n" + "=" * 50)
    print("🧪 TEST: Health Check")
    print("=" * 50)

    try:
        response = requests.get(
            "http://localhost:8000/webhook/health/",
            timeout=5
        )

        print(f"📥 Status: {response.status_code}")
        print(f"📄 Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

        return response.status_code == 200

    except requests.ConnectionError:
        print("❌ Server ishlamayapti")
        return False
    except Exception as e:
        print(f"❌ Xatolik: {e}")
        return False


def test_invalid_json():
    """Noto'g'ri JSON testi"""
    print("\n" + "=" * 50)
    print("🧪 TEST: Noto'g'ri JSON (should fail)")
    print("=" * 50)

    try:
        response = requests.post(
            WEBHOOK_URL,
            data="invalid json {{{",
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        print(f"📥 Status: {response.status_code}")
        print(f"📄 Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

        return response.status_code == 400  # Should return 400

    except Exception as e:
        print(f"❌ Xatolik: {e}")
        return False


def main():
    """Barcha testlarni ishga tushirish"""
    print("\n🚀 SELLER BOT API TEST")
    print("=" * 50)

    results = []

    # Health check
    results.append(("Health Check", test_health_check()))

    # New order
    results.append(("New Order", test_new_order()))

    # Order update
    results.append(("Order Update", test_order_update()))

    # Invalid JSON
    results.append(("Invalid JSON Handler", test_invalid_json()))

    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST NATIJALARI")
    print("=" * 50)

    passed = 0
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {name}: {status}")
        if result:
            passed += 1

    print(f"\n  Jami: {passed}/{len(results)} passed")
    print("=" * 50)


if __name__ == "__main__":
    main()
