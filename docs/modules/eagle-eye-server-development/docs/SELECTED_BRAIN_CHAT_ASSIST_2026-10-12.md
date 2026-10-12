# Selected Brain native Chat and Assist boundary

Native aipacs Chat now uses the existing company Chat backend and selected shared Brain, preserving its prompt/model construction. Server 1 report fallback remains unchanged by owner instruction. Legacy Assistant/Search remain on Server 1. Custom Brain rejects Assistant, Search and Web Search before dispatch and removes them from dynamically read capabilities; cited web search is also excluded. Switching saved Brain selection updates discovery without reconstructing the host. Personal provider handling and voice transcription are unchanged.

Backend and capability tests passed; client visual disable, live provider acceptance, Developer parity and activation are pending. No prompts or credentials changed.

## Custom EchoMind modality prompts

Owner-approved extension: Custom API reporting uses explicit user-defined MRI, CT, Sonography, Obstetrics and Cardiology prompts. These fields start empty; missing or unsupported modality prompts must fail before upstream dispatch and must not fall back to a generic/company prompt. Company G prompts remain unchanged; A/V retain company prompt ownership but remain unavailable without qualified models. Custom credentials, model and prompt fields belong to the operator. This source change does not constitute active-service or build acceptance.

Custom reporting owns only user-provided request data and the exact modality prompt. The five modality fields do not inherit the older general EchoMind prompt. Existing G workflow prompts are unchanged. Custom Chat retains its separate user-defined Other EchoMind workflows prompt. Source and automated checks are distinct from active Razi acceptance.
