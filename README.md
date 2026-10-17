# Foreman

**A shop-floor inspection agent that runs on AMD hardware the plant controls.**
PatchCore finds the defect, Gemma 4 explains why it happened, the machine manual says how to fix it, and a supervisor approves the work order. Today the whole pipeline (both models) runs on a single **AMD Ryzen 7 7435HS** laptop CPU, with no GPU and no cloud, so no camera footage leaves the building. The same code ships with a ROCm deployment for an **AMD Instinct MI300X** to run the larger Gemma 4 31B.

> AMD Developer Hackathon: ACT III · Track: **Intelligent Industry**: help factories spot problems earlier and operate better.

**Try it:** [szae444.github.io/foreman-amd-hackathon](https://szae444.github.io/foreman-amd-hackathon/) is the real UI replaying a recorded live run (PatchCore + Gemma 4 E2B on the Ryzen, CPU only). Your clicks step through the recording; nothing runs in the browser, and the long Gemma wait is fast-forwarded with the real time shown. It is recorded by `scripts/record_replay.py` and built by `scripts/build_replay_site.py`. To run it live, see [On an AMD Ryzen CPU](#on-an-amd-ryzen-cpu-with-the-real-gemma-4-the-demo).

---

## The problem

On a cold-forming line, a worn die or a misaligned transfer finger costs money twice. First you get scrap: bad parts made until someone notices. Then you get downtime while a technician looks up what the symptom means. Vision systems can flag a bad part, but they can't say *why*. The knowledge that links "scratches on the hex flats + rising ram vibration" to "die wear, see §5.1, polish per procedure 6.1, 85 Nm" is in a PDF and in the heads of senior technicians.

## What Foreman does

| Step | What happens | Where it runs |
|---|---|---|
| **1. Detect** | **PatchCore**, trained on *good parts only*, scores every part from CAM-3 and produces a heatmap of where the part differs from anything good it has seen. | PyTorch on the **AMD Ryzen** CPU (ROCm build for MI300X) |
| **2. Fuse** | Five press sensors are checked against the commissioning baseline (robust z-scores and trends; statistics, not an LLM). | CPU |
| **3. Retrieve** | Pulls the defect catalogue, the troubleshooting sections that match the sensor signature, and then **follows the manual's own cross-references** to the repair procedure (torques, tools, spares). Safety (LOTO) and containment are always included. | BM25 |
| **4. Reason** | **Gemma 4 31B (vision)** reads the photo, the heatmap, the sensor readings and the manual sections. It returns a structured diagnosis: probable cause with a confidence value, evidence by source, alternatives ruled out, a work order, containment steps, and an operator message in English and Italian. | Gemma 4 E2B on llama.cpp, **AMD Ryzen** CPU · Gemma 4 31B on **vLLM / ROCm** for MI300X |
| **5. Verify** | Every manual citation is checked against the sections the model was actually given. Invented references are struck through as *unverified*. | app |
| **6. Approve** | A supervisor approves or rejects. On approval the work order gets a number, the simulated repair runs, and the sensors visibly return to baseline. | human |

**Early warning → escalation.** Faults show up in the sensors before the camera sees defects. Foreman opens an *early-warning* incident from the sensors alone. When the camera then confirms a defect, the same incident is **escalated** and re-diagnosed with the photo. One incident, one work order, no alert storm.

## Why AMD

- **It runs on the AMD box a plant already has.** Both models run on one AMD Ryzen 7 7435HS (8 cores, 16 GB RAM), CPU only: the NVIDIA card in the same laptop is switched off for the run (`--device none`, PyTorch CPU build). An edge PC next to the press is enough for one line; nothing needs a datacenter GPU or a cloud API.
- **Self-hosted open models.** The camera footage and machine data go to a model the plant runs itself, not to a third-party API. For EU manufacturers this decides whether the system can be deployed at all.
- **Scale-up path: AMD Instinct.** The repo includes a ROCm deployment (`vllm/vllm-openai-rocm` + `rocm/pytorch`) that serves Gemma 4 31B in BF16 (~62 GB) and the detector together on one MI300X (192 GB HBM3), for a whole plant's lines from one card. *This path is built but has not been run yet: we had no Developer Cloud credits during the build week.*
- **Live proof in the UI.** The bottom rail names the detected hardware and shows its load (CPU and RAM on the Ryzen; `rocm-smi` GPU use, VRAM, power and temperature on Instinct), plus the model server's Prometheus metrics (decode tokens/s) from llama.cpp or vLLM.

## Results

PatchCore on MVTec AD `metal_nut`: the held-out test split was never used for training or setting the threshold, and the threshold comes from held-out *good* parts only.

| Run | Coreset | Image AUROC | False alarms on good parts | Scratch / bent / color / flip recall at threshold |
|---|---|---|---|---|
| AMD Ryzen 7 7435HS (CPU) | 2 % | **0.9956** | **0 %** | 78 % / 96 % / 96 % / 100 % |

Detection takes about 184 ms per image on the Ryzen.

The threshold is deliberately conservative: false stops cost more than one missed cosmetic scratch. Faint scratches are the main miss.

## Honest scope

- **Camera images are real** (MVTec AD, `metal_nut`). **Press sensors are simulated** from a commissioning spec, with physically plausible fault signatures. The UI says so on screen.
- **The FM-400 manual is fictional**, written for this demo. The retrieval and citation-checking code works with any manual in the same `## <n> <title> [p.N]` format.
- **Mock mode** (`FOREMAN_LLM_MODE=mock`) is only for working on the UI without a GPU. Every mock output is labelled `[MOCK]`, and a banner warns not to demo with it.

## Run it

### Locally (UI development, no GPU)

```bash
python -m venv .venv && . .venv/Scripts/activate        # Windows Git Bash; use .venv/bin/activate on Linux/macOS
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m foreman.detector.train --coreset 0.02         # downloads MVTec metal_nut, trains PatchCore (~2 min on CPU)
FOREMAN_LLM_MODE=mock uvicorn foreman.server:app --port 8765
```

Open http://127.0.0.1:8765, press **Start line**, then inject a fault.

### On an AMD Ryzen CPU, with the real Gemma 4 (the demo)

Uses a [llama.cpp release](https://github.com/ggml-org/llama.cpp/releases) and the `ggml-org/gemma-4-E2B-it-GGUF` files. `--device none` keeps every layer, including the vision projector, on the CPU.

```bash
llama-server -m gemma-4-E2B-it-Q4_0.gguf --mmproj mmproj-gemma-4-E2B-it-Q8_0.gguf \
  --device none -ngl 0 --no-mmproj-offload -t 8 -c 16384 --jinja --metrics \
  --port 8001 --alias google/gemma-4-E2B-it
FOREMAN_DEVICE=cpu FOREMAN_LLM_MODE=live FOREMAN_LLM_BASE_URL=http://127.0.0.1:8001/v1 \
  FOREMAN_LLM_MODEL=google/gemma-4-E2B-it uvicorn foreman.server:app --port 8765
```

On the Ryzen 7 7435HS (8 threads), Gemma 4 E2B reads the prompt at about 64 tokens/s and writes at about 12 tokens/s, so a full diagnosis (~1,000 JSON tokens) takes a median of about 2.8 minutes (1.6–5.9 min over 12 runs, on a 16 GB laptop with other apps open). The early-warning design covers that wait: the sensors open the incident before the camera sees a defect.

### On AMD Developer Cloud (scale-up path, not yet run)

Step-by-step with timings: [`docs/AMD_SETUP.md`](docs/AMD_SETUP.md).

1. Create a GPU droplet: **MI300X × 1**, **vLLM Quick Start** image, with your SSH key.
2. From your laptop: `bash deploy/push_from_laptop.sh <droplet-ip>`.
   This starts Gemma 4 on `vllm/vllm-openai-rocm` (bound to `127.0.0.1` only), builds the app on `rocm/pytorch`, trains PatchCore on the GPU, and serves the UI on `:8080`.
3. Check the full pipeline against the real model:
   `ssh root@<ip> 'cd /opt/foreman && docker compose exec foreman python -m scripts.smoke_live'`
4. **Destroy the droplet when you're done.** Billing continues even while it's powered off.

Configuration is in `.env` (see `.env.example`): model id, endpoint, detector category, tick speed.

**If the diagnosis feels slow on camera:** dense Gemma 4 31B writes about 800 JSON tokens per incident. For a snappier demo, set `FOREMAN_LLM_MODEL=google/gemma-4-26B-A4B-it` (Mixture-of-Experts, about 4B active parameters) and re-run `docker compose up -d`. Measure both with `scripts.smoke_live` and keep the one that reads better. **Rehearsing offline:** `FOREMAN_LLM_MODE=mock FOREMAN_MOCK_DELAY_S=15` simulates the reasoning wait, so you can practise the voiceover timing.

## Tested against a real Gemma 4

The live code path was run end-to-end against a real **Gemma 4 E2B** (Q4_0 GGUF), served by `llama-server` from llama.cpp, the same OpenAI-compatible API that vLLM exposes. It was developed on the laptop's RTX 4050 and then re-run CPU-only on the AMD Ryzen 7 7435HS (`scripts.smoke_live`: PASS). Each finding below became a fix and a test:

| Real-model finding | Fix |
|---|---|
| The server's Gemma 4 template had **thinking on by default**. Hidden reasoning used up the token budget, so the JSON was cut off and `§ — ×` came back as `�`. | Every request sends `chat_template_kwargs: {enable_thinking: false}`. A cut-off or invalid reply gets **one repair retry** with a bigger budget, then a clear error. |
| The model **left the sensors out** of its evidence and sometimes misread the defect type. | Foreman computes the **sensor signature** in code (sensor pattern → troubleshooting § → the defect § that links to it → defect type) and tells the model what to look for. After the diagnosis, a **consistency check** flags any camera/sensor disagreement on the ticket, and missing sensor evidence is added and labelled. |
| It pasted **whole sections** into `manual_refs`. | Citations are verified by section and page, then shown in canonical form (`§4.3 p.18`). |
| A slow first diagnosis could **finish after an escalation**, or even after a supervisor approved, and overwrite the newer state. | Jobs carry an **evidence revision**. Stale results are discarded, and an approved or rejected incident is never reopened. |

Result on the lubricant-fault scenario, run twice: early warning from the sensors → camera confirms → **"Lubrication system fault", discoloration**, citing §4.3 p.18 and §5.3 p.32 (both verified), camera and sensors agree. That takes about 18 s and about 1,050 tokens on the RTX 4050, and a median of 2.8 minutes CPU-only on the Ryzen.

**Scored evaluation** (`python -m scripts.eval_live --per-fault 3`). For each fault, the run develops the sensor signature, picks real MVTec images of the matching defect that the detector flags, runs the full pipeline, and scores the result against the simulator's ground truth:

| Gemma 4 E2B | Defect type | Camera/sensor agree | Right troubleshooting § cited |
|---|---|---|---|
| RTX 4050, before the whole-part cue | 9/12 (flips 0/3) | 9/12 | 9/12 |
| RTX 4050, after | **12/12** | **12/12** | **12/12** |
| **AMD Ryzen 7 7435HS, CPU only** | **12/12** | **12/12** | **12/12** |

The flips failed for a physical reason: a nut presented upside down has no local flaw, so PatchCore's heatmap covers the whole face. Every flagged flip covers 44–49% of the image, while every scratch, bent or discoloured part covers at most 9.5%. The detector now describes coverage of 25% or more as a *whole-part difference (wrong orientation or wrong part)*, and the model then names the orientation fault. *Caveats:* only 3 images per fault and one model, and the 25% threshold was chosen from test-set measurements (with a wide margin, but not an independent hold-out). The honesty case passes: a real scratch with healthy sensors gets a visual diagnosis with no consistency claim.

**Recommended action vs the manual:** the model's action matched the manual in 9/12 cases, on both machines. In the 3 orientation-fault cases it still said "stop line", even with an explicit prompt rule, while §5.4 says the press can keep running with the feeder in bypass. Foreman checks this in code: when a cited troubleshooting section says the press need not stop and the model recommends stopping, the ticket quotes that sentence from the manual and leaves the call to the supervisor. All 3 cases were flagged, on both machines. Ryzen results: `data/eval_ryzen/`.

To reproduce, start `llama-server` as in [Run it](#on-an-amd-ryzen-cpu-with-the-real-gemma-4-the-demo), then:

```bash
FOREMAN_DEVICE=cpu FOREMAN_LLM_MODE=live FOREMAN_LLM_BASE_URL=http://127.0.0.1:8001/v1 FOREMAN_LLM_MODEL=google/gemma-4-E2B-it python -m scripts.smoke_live
FOREMAN_DEVICE=cpu FOREMAN_LLM_MODE=live FOREMAN_LLM_BASE_URL=http://127.0.0.1:8001/v1 FOREMAN_LLM_MODEL=google/gemma-4-E2B-it python -m scripts.eval_live --per-fault 3
```

## Tests

```bash
pytest -q
```

34 tests cover:
- false-alarm rate over 500 normal ticks
- each fault tripping its own sensor
- retrieval following cross-references
- citation verification (tolerant of formatting, strict on section and page)
- the live Gemma request shape and the fallback when a server lacks structured output (against a mock OpenAI server)
- the full loop on real images (sensors before the camera → incident → approve → repair → no follow-up alarm)
- escalation from early warning to camera confirmation, including while the first diagnosis is still running
- stale results never overwriting an escalation or an approval
- the sensor signature resolving to the right defect type for every fault, and the camera/sensor consistency check
- thinking-off requests and the one-retry repair of cut-off or invalid model output

## Layout

```
foreman/
  detector/patchcore.py   PatchCore in plain PyTorch (ROCm-friendly, no anomalib)
  detector/train.py       fit + calibrate + evaluate on MVTec AD
  sensors.py              press simulator + statistical monitor
  manual.py               section parser, BM25, cross-reference following
  llm.py                  Gemma 4 via vLLM: schema, prompts, citation check, mock
  agent.py                inspect → fuse → retrieve → reason → review loop
  telemetry.py            rocm-smi / amd-smi (or CPU + RAM) + vLLM / llama.cpp metrics
  server.py               FastAPI + server-sent events
web/                      control-room UI (vanilla JS, no build step)
data/manuals/             the FM-400 manual (fictional)
deploy/                   droplet setup + push script
scripts/smoke_live.py     end-to-end check against the real endpoint
```

## Licences and credits

- MVTec AD: Bergmann et al., CVPR 2019. **CC BY-NC-SA 4.0** (non-commercial), downloaded at train time and not redistributed here.
- PatchCore: Roth et al., *Towards Total Recall in Industrial Anomaly Detection*, CVPR 2022. Re-implemented from the paper.
- Gemma 4: Google DeepMind. Check the model card for licence terms.
- Code: MIT.
