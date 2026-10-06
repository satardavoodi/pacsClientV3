# STT provider priority and targeted Whisper adaptation

## Implemented client presentation

The owner requested Google first in Settings > EchoMind > Voice to Text, followed
by the existing dedicated Whisper service. The shared provider list now displays:

1. Google Speech (`v2t`)
2. Company Server 1 (`aipacs_1`, existing dedicated Whisper)
3. Company Server 2 (`aipacs_2`)
4. Company Server 3 (`aipacs_3`)
5. OpenAI Transcription (`openai`)
6. Custom Server (`custom`)

This is a presentation-order change. Saved provider IDs, default migration,
addresses and credentials are unchanged. It does not introduce automatic
fallback, renumber the company endpoints, or point clients at the isolated V100
pilot. Settings restores selection by provider ID. Google is the existing Web
Speech integration, not Google Cloud Chirp 3. The existing client-direct STT
implementation is not evidence that all AI routes satisfy the Eagle Eye contract.

The owner-directed company inference architecture remains authenticated Eagle Eye.
Any later production deployment of a new Whisper checkpoint must use the agreed
server integration; the private V100 comparison listener is not a client endpoint.

## Evidence and training readiness

The private paired evaluation covers 30 identical recordings (43.36 minutes),
nine pipelines and 270 successful responses. Google Web Speech achieved 27.86%
normalized word-edit distance against the current review drafts; the dedicated
Whisper achieved 31.10%. Client elapsed totals were 490.41 and 78.12 seconds.
These are development results, not certified clinical accuracy. The reference
was assisted by final reports and historical training overlap is unknown.

The dataset inventory has 149 recordings, 2.90 hours. No complete recording is
currently marked human-verified, gold-eligible or training-eligible. Partial
physician corrections are retained; they do not certify every spoken word.
The 30 comparison recordings have already influenced selection and must not be
reused as an untouched final test set.

The V100 data disk contains the original trainable safetensors checkpoint as
well as the CTranslate2 inference copy. The source is Whisper with 32 encoder
and 32 decoder layers, hidden size 1280 and 128 mel bins. Continue adaptation
from that trainable source, never from the inference-only CTranslate2 binary.
No new training or checkpoint promotion has been performed.

## Proposed next experiment

1. Verify literal transcripts against audio. Keep the polished clinical report
   separate. Preserve spoken instructions, numbers, negation, laterality and
   level names. Mark uncertain intervals; do not replace them with plausible
   report wording. Use Google/custom disagreement only to prioritize review,
   not as an automatic truth label.
2. Align verified text to speech-boundary segments of approximately 10-30 seconds.
   Retain parent recording/session identity, timestamps and immutable audio hashes.
   Never train a short segment against the whole recording's transcript. Keep
   all chunks from the same recording/session in one partition and check duplicates.
3. Collect fresh sessions for a held-out evaluation set before tuning. The existing
   corpus can support development after verification. Include quiet/noisy audio,
   short commands, long dictation and Persian/English medical terminology.
4. Start with an isolated LoRA experiment on the existing custom checkpoint.
   Initial candidates: attention `q_proj`/`v_proj`, rank 16 versus 32, FP16,
   batch size 1 with gradient accumulation and gradient checkpointing. Learning
   rates such as 1e-5 and 5e-5 are trial values, not established optimal settings.
   Validate trainable module names and run a synthetic forward/backward memory
   probe before scheduling real training. Use FP16 rather than native BF16 on V100.
5. Evaluate after each epoch with early stopping; compare the frozen custom model,
   LoRA candidates and a limited decoder-adaptation candidate if LoRA underfits.
   If available, mix verified earlier/general Persian speech to check retention.
   Augmentation (mild gain, noise or speed changes) is a separate measured ablation;
   avoid blanket denoising and heavy distortion of medical terms.
6. Score normalized WER/CER and separately audit negation, numbers/units, spinal
   levels, laterality, dictation commands and physician-approved terminology.
   Report per-recording outcomes and confidence intervals, not only an aggregate
   percentage. Compare latency and GPU memory using identical decoding settings.
7. Merge/export a candidate to FP16 CTranslate2, then rerun the same verified
   holdout through VoiceTranscriptionService. Promotion requires better held-out
   transcription without worsening critical-field errors and an acceptable
   latency/memory budget. Retain the original model for rollback.

All training artifacts and caches belong under `/data` on V100. The approximately
three-hour development corpus is sufficient for a small adaptation experiment
after label review, not evidence that a particular improvement is guaranteed.
Resampling legacy 8-bit recordings cannot restore information already lost.

## Verification

- The provider-order guard failed on the previous order and passed after editing.
- 41 focused transcription and pipeline-scoping tests passed (exit 0).
- The changed provider module is byte-identical to its plugin mirror. The global
  mirror check remains blocked by pre-existing ai_chat_pages.py drift; that
  unrelated work is preserved.
- Live source GUI acceptance is blocked: the existing Test Control client could
  not connect to the local source instance. No application was launched/restarted.
  Verify the visible dropdown and retained saved selection after the human starts
  a fresh source test session outside clinical work.
- No installed build, production STT setting or model weights were changed.

## Primary implementation reference

Hugging Face's [ASR fine-tuning guide](https://huggingface.co/learn/audio-course/chapter5/fine-tuning)
documents paired audio/text preprocessing, sequence-to-sequence collation and
generated-text WER evaluation. The experiment values above are proposed settings
for this dataset and hardware, not performance guarantees from that guide.

## Owner update 2026-10-03

Automatic mode now defaults to Google Web Speech, GapGPT Whisper (aipacs_3), Company Server 1, then Company Server 2. Existing explicit selections remain manual; the current workstation was switched to Automatic at the owner request. Secretary routes through the same service as chat. Automatic attempts use at most 45 seconds per provider request; Google honors a shared deadline across chunks. HTTP timeout is a network timeout, not a hard wall-clock cancellation guarantee. This supersedes the earlier presentation-only note. Live GUI acceptance remains pending.
