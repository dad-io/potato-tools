# daasktop

It's a desktop. I'm a dad now. The math works out.

A glanceable Rainmeter panel for the right edge of an ultrawide: clock / uptime, CPU (load + 16 threads + temp), GPU (load / temp / VRAM via `nvidia-smi`), RAM, the five drives I keep meaning to clean up, network, top CPU/RAM/VRAM hogs, a green → amber → red status light, and hover-to-expand.

## Install

1. Copy the `SystemHMI` folder into `Documents\Rainmeter\Skins`
2. Refresh Rainmeter, load `Panel.ini`
3. Drag it somewhere. It's your screen, I'm not your dad. (I am, however, *a* dad.)

## Needs

- Rainmeter 4.5+ · an NVIDIA GPU (`nvidia-smi`) · [Core Temp](https://www.alcpu.com/CoreTemp/) running for CPU temp (otherwise that field just shrugs)

A hidden `poll.ps1` asks `nvidia-smi` and Core Temp how things are going every couple seconds and writes a file the skin reads. No new software, no telemetry, no nonsense.
