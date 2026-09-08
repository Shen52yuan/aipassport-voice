#!/usr/bin/env python3
"""BLE 扫描诊断：列出周围所有 BLE 设备，并特别标注 aipassport 可能的广播名。

已知广播名（实测）：
  · "AI Passport"    — folo-ai-passport-voice 配套设备端固件（含 GATT 0xA2B0，唯一可用）
  · "4c11ae326718"   — TRAE 默认固件 v1.0.2 实测广播名 = 设备 SN（MAC 去冒号）
  · "TraeWork"       — TRAE 固件 at+config=? 里的 name（注意：广播名实为 SN）
  · "FoloPassport"   — FoloToy/ai-passport 官方 main 分支 demo

⚠️ 广播名匹配到 ≠ 能用：TRAE 固件不含 GATT 0xA2B0，连上也无法传音频。
   扫到后务必跑 probe_gatt.py 确认服务是否存在。

用法：
    python scan_ble.py          # 默认扫 15s
    python scan_ble.py 25       # 扫 25s

⚠️ 设备 standby_time 默认 300 秒（5 分钟无操作进待机，BLE 停止广播）。
   扫描前请按一下设备按键唤醒它，否则扫不到。
"""
import asyncio
import re
import sys

# 设备 SN（12 位十六进制小写）—— 从 at+config=? 的 sn= 字段取得
DEVICE_SN = "4c11ae326718"
TARGETS = ["AI Passport", DEVICE_SN, "TraeWork", "FoloPassport"]
HEX12 = re.compile(r"^[0-9a-f]{12}$", re.I)


async def main(timeout: float):
    from bleak import BleakScanner

    print(f"[scan] 扫描 {timeout:g} 秒 …")
    print(f"[scan] 关注广播名: {', '.join(TARGETS)}")
    print("[scan] 若刚开机请忽略；否则先按一下设备按键唤醒（待机 300s 会停广播）\n")
    try:
        devs = await BleakScanner.discover(timeout=timeout)
    except Exception as e:
        print(f"[scan] 扫描失败: {e!r}")
        print("       检查：系统设置 → 隐私与安全性 → 蓝牙 → 勾选「终端」")
        return

    if not devs:
        print("[scan] 一个设备都没扫到 → 蓝牙权限/开关问题")
        return

    hits = []
    print(f"[scan] 共发现 {len(devs)} 个设备：")
    for d in sorted(devs, key=lambda x: (x.name or "")):
        name = d.name or "(无名)"
        rssi = getattr(d, "rssi", "?")
        mark = ""
        for t in TARGETS:
            if d.name and t.lower() in d.name.lower():
                mark = f"   <<<< 命中目标 [{t}]"
                hits.append((name, d.address))
                break
        else:
            # 形如 4c11ae326718 的 12 位十六进制名 = 极可能是本机 SN（TRAE 固件）
            if d.name and HEX12.match(d.name.strip()):
                mark = "   <<<< 疑似设备 SN"
                hits.append((name, d.address))
        print(f"  - {name:<32} address={d.address}  rssi={rssi}{mark}")

    print()
    if hits:
        for name, addr in hits:
            print(f"[OK] 命中：{name}   UUID={addr}")
        print()
        print("[!] 广播名匹配 ≠ 能用。下一步必跑（确认有没有音频 GATT 服务）：")
        print(f"    python probe_gatt.py {hits[0][1]}")
        return

    print(f"[!] 未发现 {TARGETS} 中任何一个。")
    print("    1) 按一下设备按键唤醒（待机 5 分钟会停广播）后重试")
    print("    2) 确认设备已开机（按住电源键 0.5 秒）")
    print("    3) 若列表里出现其它疑似名字，把它发我")


if __name__ == "__main__":
    t = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    asyncio.run(main(t))
