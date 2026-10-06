"""Synthetic optimizer/checkpoint capacity proof; no medical training claims."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import torch
from run_deepmica_screen import load_checkpoint


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--weights',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('Existing capacity receipt.')
    torch.set_num_threads(4)
    torch.manual_seed(20261002)
    free,total=torch.cuda.mem_get_info()
    if free<9*2**30:raise RuntimeError('Insufficient shared-host memory.')
    torch.cuda.set_per_process_memory_fraction(8*2**30/total)
    model,epoch=load_checkpoint(args.source,args.weights)
    model.cuda().train()
    optimizer=torch.optim.AdamW(model.parameters(),lr=3e-6)
    report={'status':'synthetic_only_capacity_proof','medical_optimizer_steps':0,
            'initial_checkpoint_epoch':epoch,'runs':[],'precision':'FP32',
            'checkpoint_sha256':hashlib.sha256(args.weights.read_bytes()).hexdigest()}
    started=time.monotonic()
    initial=model.outputs.weight.detach().clone()
    for batch in (1,2,4):
        torch.cuda.reset_peak_memory_stats()
        image=torch.rand(batch,1,256,256,device='cuda')*.2
        truth=torch.zeros_like(image)
        truth[:,:,100:103,100:103]=1
        image[:,:,100:103,100:103]=.9
        optimizer.zero_grad(set_to_none=True)
        logits=model(image)
        loss=torch.nn.functional.binary_cross_entropy_with_logits(logits,truth)
        if not torch.isfinite(loss):raise RuntimeError('Nonfinite synthetic loss.')
        loss.backward()
        gradient=torch.nn.utils.clip_grad_norm_(model.parameters(),5,error_if_nonfinite=True)
        optimizer.step()
        report['runs'].append({'batch':batch,'loss':float(loss.detach()),
            'gradient_norm':float(gradient),'peak_vram_gib':torch.cuda.max_memory_allocated()/2**30})
        del image,truth,logits,loss
    if torch.equal(initial,model.outputs.weight.detach()):raise RuntimeError('No optimizer change.')
    state=args.output.with_suffix('.synthetic.pth')
    torch.save(model.state_dict(),state)
    model.load_state_dict(torch.load(state,map_location='cuda',weights_only=True),strict=True)
    model.eval()
    with torch.inference_mode():
        output=model(torch.zeros(1,1,256,256,device='cuda'))
        if not torch.isfinite(output).all():raise RuntimeError('Invalid checkpoint reload.')
    report.update(successful_synthetic_updates=3,checkpoint_reload=True,seconds=time.monotonic()-started,
                  limitations=['synthetic capacity only; not accuracy or clinical adaptation',
                               'larger batches not measured while active EchoMind sessions exist'])
    args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
