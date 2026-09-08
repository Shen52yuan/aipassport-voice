#!/usr/bin/env python3
"""GATT 探针：连上指定 BLE 设备，列出它提供的全部服务/特征，判定能否用于 relay.py。

为什么需要它：
  relay.py 只认 GATT 服务 0000A2B0-0000-1000-8000-00805F9B34FB，
  下含 0xA2B1(CTRL,写) / 0xA2B2(EVENT,通知) / 0xA2B3(AUDIO,通知)。
  广播名能对上不代表服务存在 —— TRAE 默认固件（广播名=SN）就没有这套服务。

用法：
    python probe_gatt.py                       # 先按名字扫，扫到就自动连
    python probe_gatt.py 03C18CD7-85B8-52D7-F9CA-D375531D5474
                                               # 直接连（macOS 用 CoreBluetooth UUID）

⚠️ 必须在你自己的 Mac 终端跑（WorkBuddy 沙箱拦 CoreBluetooth）。
⚠️ 设备待机 300s 会停广播，跑之前按一下按键唤醒。
"""
import asyncio
import sys

SERVICE_UUID = "0000a2b0-0000-1000-8000-00805f9b34fb"
WANTED = {
    "0000a2b1-0000-1000-8000-00805f9b34fb": "CTRL  (Mac→设备, JSON 行)",
    "0000a2b2-0000-1000-8000-00805f9b34fb": "EVENT (设备→Mac, JSON 行)",
    "0000a2b3-0000-1000-8000-00805f9b34fb": "AUDIO (设备→Mac, 音频帧)",
}
CANDIDATE_NAMES = ["AI Passport", "4c11ae326718", "TraeWork", "FoloPassport"]


async def resolve_address(arg: str | None) -> str | None:
    if arg:
        return arg
    from bleak import BleakScanner

    print("[probe] 未提供地址，先扫描 …")
    for name in CANDIDATE_NAMES:
        d = await BleakScanner.find_device_by_name(name, timeout=12)
        if d:
            print(f"[probe] 按名字命中 {name!r} → {d.address}")
            return d.address
    print("[probe] 四个候选名都没扫到 → 先跑 scan_ble.py 看真实广播名")
    return None


async def main(addr_arg: str | None):
    from bleak import BleakClient

    addr = await resolve_address(addr_arg)
    if not addr:
        return

    print(f"\n[probe] 连接 {addr} …")
    try:
        async with BleakClient(addr, timeout=25.0) as client:
            print(f"[probe] 已连接 (MTU={client.mtu_size})")
            svcs = list(client.services)
            print(f"[probe] 共 {len(svcs)} 个服务：\n")

            hit_service = False
            found_chars = set()
            for s in svcs:
                mark = ""
                if s.uuid.lower() == SERVICE_UUID:
                    mark = "   <<<<<< 目标服务 0xA2B0"
                    hit_service = True
                print(f"  service {s.uuid}  ({s.description or '?'}){mark}")
                for c in s.characteristics:
                    cu = c.uuid.lower()
                    cname = WANTED.get(cu)
                    if cname:
                        found_chars.add(cu)
                    props = ",".join(c.properties)
                    tail = f"   <<<<<< {cname}" if cname else ""
                    print(f"      char {c.uuid}  props=[{props}]{tail}")
                print()

            print("=" * 62)
            if hit_service and len(found_chars) == 3:
                print("✅ 设备提供完整 0xA2B0 音频服务（CTRL/EVENT/AUDIO 齐全）")
                print("   → 这个固件可用。直接跑：")
                print(f"     python relay.py --device {addr}")
            elif hit_service:
                miss = [WANTED[u] for u in WANTED if u not in found_chars]
                print("⚠️ 有 0xA2B0 服务但特征不全，缺：", ", ".join(miss))
                print("   → 固件版本可能不匹配，考虑刷配套语音固件")
            else:
                print("❌ 未发现 0xA2B0 音频服务 → 当前固件不是配套语音固件")
                print("   即使用 --device 强行指定地址，relay.py 也会因找不到服务而失败。")
                print("   解决：刷 folo-ai-passport-voice 的设备端固件（ESP-IDF 编译）。")
                print("   （该固件广播名为 'AI Passport'，见 main/ble_audio.c:118）")
    except Exception as e:
        print(f"[probe] 连接失败: {e!r}")
        print("       常见原因：设备待机(按按键唤醒) / 蓝牙未授权给终端 / 地址过期(UUID 会变)")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
