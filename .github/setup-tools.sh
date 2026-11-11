#!/usr/bin/env bash
# Installs ffmpeg, fonts and the Python packages for every pipeline run.
# Every download has a time limit, and if Ubuntu's servers don't answer (it happens on GitHub's
# machines), ffmpeg and the DejaVu fonts come from backup copies on GitHub instead.
set -uo pipefail
DV=/usr/share/fonts/truetype/dejavu
have_ffmpeg() { command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null \
                && ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles "; }
have_fonts() { [ -f "$DV/DejaVuSans-Bold.ttf" ]; }

if ! have_ffmpeg || ! have_fonts; then
  APT="-o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20"
  if timeout 240 sudo apt-get update -qq $APT && \
     timeout 360 sudo apt-get install -y -qq $APT ffmpeg fonts-dejavu-core > /dev/null; then
    echo "Video tools installed from Ubuntu."
  else
    echo "::warning::Ubuntu's download servers didn't answer — using backup copies from GitHub."
  fi
fi

if ! have_ffmpeg; then
  tmp=$(mktemp -d)
  curl -sSfL --retry 3 --max-time 300 -o "$tmp/ff.tar.xz" \
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz" \
    && tar -xJf "$tmp/ff.tar.xz" -C "$tmp" \
    && sudo cp "$tmp"/ffmpeg-*/bin/ffmpeg "$tmp"/ffmpeg-*/bin/ffprobe /usr/local/bin/ \
    && echo "ffmpeg installed from the GitHub backup."
fi

if ! have_fonts; then
  tmp=$(mktemp -d)
  curl -sSfL --retry 3 --max-time 120 -o "$tmp/dv.tar.bz2" \
    "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2" \
    && tar -xjf "$tmp/dv.tar.bz2" -C "$tmp" \
    && sudo mkdir -p "$DV" && sudo cp "$tmp"/dejavu-fonts-ttf-2.37/ttf/*.ttf "$DV/" \
    && (fc-cache -f > /dev/null 2>&1 || true) && echo "Fonts installed from the GitHub backup."
fi

mkdir -p assets/fonts
for f in ofl/anton/Anton-Regular.ttf ofl/bebasneue/BebasNeue-Regular.ttf apache/specialelite/SpecialElite-Regular.ttf ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf; do
  curl -sSfL --retry 2 --max-time 60 -o "assets/fonts/$(basename $f)" "https://github.com/google/fonts/raw/main/$f" \
    || echo "font $f skipped"
done

timeout 600 pip install -q --retries 3 --timeout 30 -r requirements.txt || { echo "::error::Python packages didn't install"; exit 1; }
have_ffmpeg || { echo "::error::ffmpeg couldn't be installed from Ubuntu or the backup"; exit 1; }
have_fonts || { echo "::error::Fonts couldn't be installed from Ubuntu or the backup"; exit 1; }
echo "Setup OK: $(ffmpeg -version | head -1)"
