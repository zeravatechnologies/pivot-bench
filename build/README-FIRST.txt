Pivot Benchmark __VERSION__ (Windows, portable)

1. Unzip this folder anywhere (for example C:\Users\<you>\PivotBenchmark).
2. This build is not code-signed. Before the first run, check the zip's SHA-256
   against SHA256SUMS.txt from the same release:
       Get-FileHash .\PivotBenchmark-__VERSION__-windows-x64.zip -Algorithm SHA256
   Then double-click PivotBenchmark.exe. Windows shows "Windows protected your PC":
   click "More info", then "Run anyway".
3. The app opens in its own window. Your settings and results are kept in
   %APPDATA%\Pivot Benchmark, not in this folder.
4. To test a local model you need llama.cpp running on this computer; the Run
   tab explains how to get it and links the download. To use Gemini as the
   adversary you need your own Gemini API key (Settings tab).

Preview: the automatic classifier is under review; numbers may change in 1.0.
Licence: GPL-3.0-or-later, LICENSE.md and NOTICE.txt in this folder.
Third-party components and their licences: THIRD-PARTY-NOTICES.txt.
Downloads and checksums: https://github.com/zeravatechnologies/releases
Documentation: https://www.zeravatech.ca/products/pivot-benchmark/
