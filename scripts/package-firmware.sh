#!/bin/sh
# 把 idf.py build 的产物打包成可直接刷写的镜像。
#
# 产出（都放在 dist/）：
#   <prefix>-full.bin            合并镜像（bootloader+分区表+app），Web Flasher 选这一个，烧到 0x0
#   <prefix>-app.bin             仅应用
#   <prefix>-bootloader.bin      仅 bootloader
#   <prefix>-partition-table.bin 仅分区表
#   SHA256SUMS                   校验值
#
# 用法：sh scripts/package-firmware.sh [build目录] [输出目录] [版本]
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${1:-build}
output_dir=${2:-dist}
version=${3:-dev}

case "$build_dir" in /*) ;; *) build_dir="$project_dir/$build_dir" ;; esac
case "$output_dir" in /*) ;; *) output_dir="$project_dir/$output_dir" ;; esac

bootloader_image="$build_dir/bootloader/bootloader.bin"
partition_image="$build_dir/partition_table/partition-table.bin"

# 应用镜像名 = 工程名，不同仓库不一样，这里按“build 根目录下的 .bin”动态取
app_image=""
for candidate in "$build_dir"/*.bin; do
    [ -f "$candidate" ] || continue
    case "$(basename "$candidate")" in
        merged*|*-full.bin) continue ;;
    esac
    app_image="$candidate"
    break
done

for image in "$bootloader_image" "$partition_image"; do
    [ -f "$image" ] || { printf '缺少构建产物: %s\n请先跑 idf.py build\n' "$image" >&2; exit 1; }
done
[ -n "$app_image" ] || { printf '在 %s 下找不到应用镜像(*.bin)\n' "$build_dir" >&2; exit 1; }

mkdir -p "$output_dir"
prefix="aipassport-voice-$version"

cd "$project_dir"
python -m esptool --chip esp32c3 merge_bin \
    --output "$output_dir/$prefix-full.bin" \
    --format raw \
    --flash_mode dio \
    --flash_freq 80m \
    --flash_size 8MB \
    0x0     "$bootloader_image" \
    0x8000  "$partition_image" \
    0x10000 "$app_image"

cp "$app_image"                  "$output_dir/$prefix-app.bin"
cp "$bootloader_image"           "$output_dir/$prefix-bootloader.bin"
cp "$partition_image"            "$output_dir/$prefix-partition-table.bin"

(
    cd "$output_dir"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$prefix"-*.bin > SHA256SUMS
    else
        shasum -a 256 "$prefix"-*.bin > SHA256SUMS
    fi
)

printf '固件已打包到 %s\n' "$output_dir"
ls -l "$output_dir"
