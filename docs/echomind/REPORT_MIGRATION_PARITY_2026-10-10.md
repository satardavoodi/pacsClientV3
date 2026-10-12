# Report migration parity review - 2026-10-10

The unified Report Send path omitted the study profile previously passed by
Turbo. HEAD history shows the former remote Turbo handler forwarding
`study_profile=_gate`; the current worker sent text, modality, template and
attachments only. Restore `_build_gate_profile(sent_text)` inside that worker
and forward the result. Existing metadata reading remains off the GUI thread.
No prompts, model choices, credentials or clinical policies were changed.

## Comparison evidence

For CT, MRI, radiography, sonography and echocardiography, with and without a
synthetic normal template, current desktop and hosted shared prompt outputs
are equal after stripping trailing line whitespace. CT and echocardiography
are also byte-identical. MRI/radiography/sonography differences are trailing
whitespace only. Turbo builder and module library sources match after import
namespace normalization. Both primary model defaults are gpt-5.6-terra with
the same AIPACS_ECHOMIND_PRIMARY_MODEL override; active process environment
and central Brain model selection still require server-side evidence.

Existing desktop instructions explicitly generate normal findings for relevant
regions when no normal template is supplied. CT instructions request numbered
lists when multiple findings exist. The ten live synthetic cases used sparse
input, no template and no study profile. Added normals and single-item numbering
variation therefore do not prove migration-induced prompt drift. The MRI
negative diffusion statement under pathology remains an observed organization
issue, not a demonstrated changed instruction. Preserve these observations;
do not change clinical policy or model to make examples pass.

The real GUI selects normal-template text before scheduling and the worker
forwards it. Native-adapter offline testing separately verified template bytes
and server prompt override composition. This does not prove GUI template selection
or exact upstream serialization in the active server process.

## Verification and pending gates

The extracted actual Send worker regression test failed before the fix because
no study gate was built or forwarded. After the fix, 22 focused tests passed
covering that boundary, single Send transport and hosted fallback policy.
Scoped EchoMind payload mirror was synchronized. Razi immutable reconciliation,
active source parity and affected-workflow live GUI acceptance remain pending
with the server coordinator; no provider call or service change was performed.
