# MiniAgent

**MiniAgent** adalah framework agentic AI open-source (Python 3.11+) dengan akses shell nyata yang ter-sandbox — bukan simulasi. Agent bisa diajak ngobrol, menulis kode, dan mengeksekusi command sungguhan melalui lapisan permission berlapis.

```
you › buat file salam.txt berisi: halo dari miniagent
$ echo halo dari miniagent > salam.txt   (safe)      <- SAFE = jalan otomatis
```

## Fitur

| Modul | Fungsi |
|---|---|
| `miniagent.executor` | SubprocessExecutor dengan workspace containment, timeout, audit log |
| `miniagent.executor.permission` | Klasifikasi risiko per command: SAFE / CAUTION / DANGEROUS / BLOCKED |
| `miniagent.llm` | Klien multi-provider via LiteLLM + fallback + streaming + auto-pick model gratis |
| `miniagent.skills` | Sistem skill dari folder `SKILL.md` + installer git yang divalidasi |
| `miniagent.pipeline` | Pipeline reasoning 10-stage dengan router kompleksitas |
| `miniagent.cli` | CLI interaktif: `chat`, `pipeline`, `doctor`, `skills`, `version` |

## Instalasi

```bash
git clone https://github.com/Putpy0/MiniAgent.git
cd MiniAgent
pip install -e .
miniagent version
```

Dependensi: `litellm`, `typer`, `rich`, `pydantic`, `pyyaml`, `python-dotenv`. Python ≥ 3.11.

## Konfigurasi & API key

Salin `miniagent/config.example.yaml` → `config.yaml`, lalu sediakan key OpenRouter:

```powershell
# opsi 1: environment variable
[Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY','sk-or-v1-...','User')
# opsi 2: file di samping config.yaml
Set-Content -NoNewline .openrouter_key "sk-or-v1-..."
```

Variabel `${ENV_VAR}` di config di-resolve otomatis; variabel yang tidak diset memicu **warning eksplisit** (tidak lagi senyap).

## CLI

| Command | Fungsi |
|---|---|
| `miniagent chat` | REPL agent interaktif — model bisa mengusulkan command; SAFE jalan otomatis, DANGEROUS konfirmasi y/N, BLOCKED selalu ditolak. Slash: `/help /reset /model /models /history /exit` |
| `miniagent pipeline "<task>"` | Jalankan reasoning pipeline 10-stage pada sebuah task |
| `miniagent doctor [--config x.yaml]` | Cek config, model, API key, dependensi |
| `miniagent skills <dir>` | Daftar skill terdeteksi |
| `miniagent version` | Versi |

Streaming: jawaban chat ditampilkan progresif (`chat_stream()`); kalau primary model gagal total (429/guardrail/outage), CLI **auto-probe kandidat model gratis** dan mengulang pesan Anda sekali dengan model pertama yang hidup.

### Protokol tool-call

Model tidak pernah mengeksekusi apa pun sendiri. Ia mengusulkan command dalam blok ` ```run `; host yang:
1. Mengklasifikasi dengan `PermissionChecker`,
2. Memeriksa semua argumen path-like tetap di dalam workspace,
3. Baru menjalankan via `SubprocessExecutor` (audit log tertulis dulu sebelum raise).

Output nyata di-feed balik ke percakapan sehingga model bereaksi pada fakta, bukan imajinasi.

## Model keamanan

| Level | Perilaku | Contoh |
|---|---|---|
| `SAFE` | Jalan tanpa konfirmasi | `echo`, `ls`, `git status`, `node server.js` |
| `CAUTION` | Log warning, jalan | `ls \| grep x` |
| `DANGEROUS` | Wajib `confirmation_callback`; tanpa callback = **fail-closed** | `cp`, `env`, `pip install`, `npm run`, `make`, `dd of=file` |
| `BLOCKED` | Selalu ditolak, tak bisa di-bypass | fork bomb, `mkfs`, `dd of=/dev/sda`, `rm -rf /` |

Proteksi aktif yang teruji (pytest + smoke test):
- Workspace containment untuk path absolut/relatif, `~`, drive-letter Windows, UNC, traversal `../` maupun `..\`
- Penolakan symlink escape saat read/write file
- Filter env sensitif (`*_API_KEY`, dsb.) dari subprocess
- Guard inline-execution: `python -c` (semua bentuk), `node -e/-p`, `vim -c`
- Guard package/script runners: `npm i/run/test/start`, `npx`, `cargo install/run`, `make`
- Validasi branch git & sanitasi nama skill (anti argument-injection & traversal)

## Sandbox (Windows)

Contoh profil sandbox ketat tersedia sebagai skrip siap pakai (lihat `C:\miniagent-sandbox` bila Anda menjalankan setup lokal):

```powershell
run_sandboxed.ps1 [-AllowLLM] <target>   # TEMP redirect + scrub env kredensial + config lock
verify_sandbox.py                        # battery escape-attempt -> harus 9/9 PASS
agent_llm_demo.py                        # demo LLM gratis + agent loop
set_key.ps1                              # simpan key dengan ACL terkunci
```

Prinsipnya: direktori kerja terisolasi (ACL terbatas), semua temp file lahir di dalam sandbox, dan tidak ada satu pun kredensial yang dibawa ke child process.

## Pipeline reasoning 10-stage

```
Intent -> Requirement -> Research -> Planning -> Architecture ->
Implementation -> Self-Review -> Execution -> Validation -> Finalization
```

- Router kompleksitas: `simple=[1,6,8,10]`, `medium=[1,2,4,6,7,8,9,10]`, `complex=semua`
- Stage 1 mendeteksi ambiguitas → pipeline berhenti sopan bila butuh klarifikasi
- Stage 8 dieksekusi host (bukan model) lewat executor sandbox penuh
- Fail-soft per stage (kecuali Intent), retry JSON 3x dengan backoff, pemulihan `<think>...</think>` untuk reasoning models

Template prompt tiap stage ada di `miniagent/prompts/*.md` — bisa Anda sunting tanpa menyentuh kode.

## Testing

```bash
python -m pytest tests/                              # 147 test offline
python miniagent/executor/_manual_check_hotfix.py    # smoke 8/8 (butuh coreutils Git di Windows)
```

## Roadmap

- [ ] Memory persisten antar sesi
- [ ] Skills runtime (entrypoint `run.py`)
- [ ] Docker executor profile
- [ ] Validasi otomatis artefak hasil Execution stage

## Lisensi

MIT — lihat [LICENSE](LICENSE).
