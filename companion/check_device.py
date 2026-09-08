#!/usr/bin/env python3
"""aipassport 一键体检：判断设备当前处于哪种状态，并给出下一步。

用法（真机 Mac 终端）：
    python check_device.py

检查三件事：
  1. USB 串口是否存在（VID 0x303A / PID 0x1001）
  2. 控制台是否有回显（→ 应用固件是否在跑）
  3. BLE 是否广播 "AI Passport"

前置动作（很重要）：
  先关掉所有连过设备的浏览器标签页（刷机页 / TRAÉ 页），再拔插 USB，
  否则 esptool 会一直把芯片按在下载模式，三项检查必然全灭。
"""
import asyncio
import glob
import time

import serial

TARGET_BLE = "AI Passport"


def find_ports():
    try:
        from serial.tools import list_ports
        ports = [p.device for p in list_ports.comports()
                 if getattr(p, "vid", None) and f"{p.vid:04X}" == "303A"]
        if ports:
            return ports
    except Exception:
        pass
    return sorted(glob.glob("/dev/cu.usbmodem*"))


def probe_console(port, per_cmd=2.0):
    """发几条控制台命令，看有没有回显。返回 (文本, 错误信息)。"""
    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
    except Exception as e:
        return None, f"打开失败: {e!r}（可能被浏览器标签页占用）"
    out = b""
    try:
        for cmd in (b"\r\n", b"st\r\n", b"help\r\n"):
            ser.write(cmd)
            t0 = time.time()
            while time.time() - t0 < per_cmd:
                chunk = ser.read(512)
                if not chunk:
                    break
                out += chunk
    finally:
        ser.close()
    return out.decode("utf-8", "replace").strip(), None


async def ble_scan(secs=12.0):
    try:
        from bleak import BleakScanner
        d = await BleakScanner.find_device_by_name(TARGET_BLE, timeout=secs)
        return (d.address if d else None), None
    except Exception as e:
        return None, f"扫描异常: {e!r}（检查蓝牙授权）"


def main():
    print("=" * 62)
    print("aipassport 设备体检")
    print("=" * 62)

    # 1) 串口
    ports = find_ports()
    print(f"\n[1/3] USB 串口: {ports if ports else '未发现'}")
    if not ports:
        print("      → 确认数据线已插、设备开机（充电-only 线不出串口）")
        return
    port = ports[0]

    # 2) 控制台
    text, err = probe_console(port)
    print(f"\n[2/3] 控制台探测 ({port})")
    if err:
        print(f"      {err}")
        console_alive = False
    elif text:
        print(f"      有回显 {len(text)} 字节：")
        for line in text.splitlines()[:15]:
            print(f"        | {line}")
        console_alive = True
    else:
        print("      无回显（发 \\r\\n / st / help 均无响应）")
        console_alive = False

    # 3) BLE
    print(f"\n[3/3] BLE 扫描（{TARGET_BLE}，12s）…")
    ble_addr, ble_err = asyncio.run(ble_scan())
    if ble_err:
        print(f"      {ble_err}")
    elif ble_addr:
        print(f"      发现！UUID = {ble_addr}")
    else:
        print("      未发现")

    # 结论
    print("\n" + "=" * 62)
    print("结论与下一步")
    print("=" * 62)
    if ble_addr:
        print("✅ BLE 广播正常 —— 应用固件在跑。")
        print("   1) 把 config.local.json 的 \"channel\" 改回 \"ble\"")
        print(f"   2) 运行：relay.py --device {ble_addr}")
        return
    if console_alive:
        print("⚠️  固件在运行、控制台可用，但 BLE 没广播。")
        print("   1) 串口工具连上去执行 `mode usb`，重启设备")
        print("   2) config.local.json 保持 \"channel\": \"usb\"，运行 relay.py")
        return
    print("❌ 设备完全无响应（无控制台、无 BLE、无 usb_link）。")
    print("   最常见原因：还卡在 esptool 下载模式。请依次：")
    print("   1) 关掉所有连过设备的浏览器标签页（刷机页 / TRAÉ 页）")
    print("   2) 拔掉 USB，等 3 秒，再插上（或按设备 Reset）")
    print("   3) 重跑：python check_device.py")
    print("   若重跑仍三项全灭 → 设备内很可能没有应用固件，需要考虑刷官方固件。")


if __name__ == "__main__":
    main()
