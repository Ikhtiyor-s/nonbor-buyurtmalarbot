import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def ami_make_call(phone: str) -> bool:
    """Asterisk AMI orqali sotuvchiga qo'ng'iroq qilish (faqat CHECKING buyurtmalar uchun)"""
    host_port = os.getenv('AMI_HOST', '172.29.124.85:5038')
    if ':' in host_port:
        host, port = host_port.rsplit(':', 1)
        port = int(port)
    else:
        host, port = host_port, 5038

    ami_user = os.getenv('AMI_USER', 'autodialer')
    ami_secret = os.getenv('AMI_SECRET', 'autodialer123')
    caller_id = os.getenv('CALLER_ID', '+998783331002')
    endpoint = os.getenv('PJSIP_ENDPOINT', 'sarkor-endpoint')
    sounds_path = os.getenv('ASTERISK_SOUNDS_PATH', '/tmp/autodialer')

    clean_phone = phone.strip()
    if not clean_phone.startswith('+'):
        clean_phone = '+' + clean_phone.lstrip('+')

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=10
        )

        await asyncio.wait_for(reader.readline(), timeout=5)

        writer.write(
            f"Action: Login\r\n"
            f"Username: {ami_user}\r\n"
            f"Secret: {ami_secret}\r\n"
            f"\r\n"
            .encode()
        )
        await writer.drain()

        login_resp = b""
        while b"\r\n\r\n" not in login_resp:
            chunk = await asyncio.wait_for(reader.read(512), timeout=5)
            if not chunk:
                break
            login_resp += chunk

        if b"Success" not in login_resp:
            logger.error(f"AMI login muvaffaqiyatsiz: {login_resp.decode(errors='ignore')[:200]}")
            writer.close()
            return False

        channel = f"PJSIP/{clean_phone}@{endpoint}"
        action_id = f"autodialer_{clean_phone}_{int(asyncio.get_event_loop().time())}"

        writer.write((
            f"Action: Originate\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: {channel}\r\n"
            f"CallerID: <{caller_id}>\r\n"
            f"Application: Playback\r\n"
            f"Data: {sounds_path}/order_reminder\r\n"
            f"Timeout: 30000\r\n"
            f"Async: yes\r\n"
            f"\r\n"
        ).encode())
        await writer.drain()

        orig_resp = b""
        for _ in range(10):
            try:
                chunk = await asyncio.wait_for(reader.read(512), timeout=3)
                if not chunk:
                    break
                orig_resp += chunk
                if b"\r\n\r\n" in orig_resp:
                    break
            except asyncio.TimeoutError:
                break

        logger.info(f"AMI Originate {clean_phone}: {orig_resp.decode(errors='ignore')[:300]}")

        writer.write(b"Action: Logoff\r\n\r\n")
        await writer.drain()
        writer.close()

        return b"Error" not in orig_resp or b"Queued" in orig_resp or b"Success" in orig_resp

    except asyncio.TimeoutError:
        logger.error(f"AMI timeout: {host}:{port}")
        return False
    except ConnectionRefusedError:
        logger.error(f"AMI ulanish rad etildi: {host}:{port}")
        return False
    except Exception as e:
        logger.exception(f"AMI qo'ng'iroq xatosi ({clean_phone}): {e}")
        return False
