"""Score requested TTS text; acoustic/reference ambiguities must be reported separately."""
import argparse
import collections
import json
from pathlib import Path
import re
import statistics
import unicodedata
from num2words import num2words


def normalize(text):
    text=unicodedata.normalize('NFKC',text).lower().replace('ß','ss').replace('%',' prozent ').replace('€',' euro ')
    def clock(m):return f'{num2words(int(m[1]),lang="de")} uhr {num2words(int(m[2]),lang="de")}'
    text=re.sub(r'\b(\d{1,2})[:.](\d{2})\s*uhr\b',clock,text)
    def number(m):
        raw=m[0].replace(',','.')
        if '.' in raw:
            whole,fraction=raw.split('.')
            if set(fraction)=={'0'}:return num2words(int(whole),lang='de')
            return num2words(int(whole),lang='de')+' komma '+' '.join(num2words(int(c),lang='de') for c in fraction)
        return num2words(int(raw),lang='de')
    text=re.sub(r'\d+(?:[.,]\d+)?',number,text).replace('ß','ss')
    text=''.join(c if c.isalnum() or c.isspace() else ' ' for c in text)
    return ' '.join(text.split())


def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        new=[i]
        for j,y in enumerate(b,1):new.append(min(row[j]+1,new[-1]+1,row[j-1]+(x!=y)))
        row=new
    return row[-1]


def score(ref,text):
    a,b=normalize(ref),normalize(text)
    return {'word_errors':distance(a.split(),b.split()),'word_count':len(a.split()),
            'char_errors':distance(a.replace(' ',''),b.replace(' ','')),'char_count':len(a.replace(' ','')),
            'exact':a==b}


def summarize(rows,manifest):
    result={}
    for system in ('redux','whisper'):
        sysrows=[x for x in rows if x['system']==system]
        groups={'all_speech':[x for x in sysrows if x['kind']!='control']}
        for condition in ('clean','noise_10dB','noise_0dB','silence'):
            groups[condition]=[x for x in sysrows if x['condition']==condition]
        for kind in ('command','numbers','names','dictation','long'):
            groups['clean_'+kind]=[x for x in sysrows if x['condition']=='clean' and x['kind']==kind]
        stats={}
        for label,items in groups.items():
            if not items:continue
            scores=[score(manifest[x['id']]['text'],x['text']) for x in items]
            words=sum(s['word_count'] for s in scores);chars=sum(s['char_count'] for s in scores)
            times=[x['seconds'] for x in items]
            slots=[]
            for row in items:
                expected=manifest[row['id']].get('slots')
                if expected:
                    hyp=' '+normalize(row['text'])+' '
                    slots.append(all(' '+normalize(s)+' ' in hyp for s in expected))
            stats[label]={'n':len(items),'unique_clips':len({x['id'] for x in items}),
                          'median_seconds':statistics.median(times),'min_seconds':min(times),'max_seconds':max(times),
                          'p95_seconds':sorted(times)[max(0,__import__('math').ceil(.95*len(times))-1)] if len(items)>=40 else None,
                          'audio_seconds_per_wall_second':sum(x['duration'] for x in items)/sum(times),
                          'wer_percent':100*sum(s['word_errors'] for s in scores)/words if words else None,
                          'cer_percent':100*sum(s['char_errors'] for s in scores)/chars if chars else None,
                          'exact_count':sum(s['exact'] for s in scores),
                          'slots_correct':sum(slots) if slots else None,'slots_total':len(slots)}
            if 'post_audio_seconds' in items[0]:
                lat=[x['post_audio_seconds'] for x in items]
                stats[label]['median_post_audio_seconds']=statistics.median(lat)
                stats[label]['min_post_audio_seconds']=min(lat);stats[label]['max_post_audio_seconds']=max(lat)
        result[system]=stats
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();out=Path(a.directory)
    manifest={x['id']:x for x in json.loads((out/'manifest.json').read_text(encoding='utf-8'))}
    result={};details={}
    for mode in ('http','realtime'):
        path=out/f'results-{mode}.jsonl'
        if not path.exists():continue
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        result[mode]=summarize(rows,manifest)
        details[mode]=[]
        for key in manifest:
            item={'id':key,'reference':manifest[key]['text'],'systems':{}}
            for system in ('redux','whisper'):
                selected=[x for x in rows if x['id']==key and x['system']==system]
                if not selected:continue
                item['systems'][system]={'median_seconds':statistics.median(x['seconds'] for x in selected),
                                          'outputs':[{'text':t,**score(manifest[key]['text'],t)} for t in sorted({x['text'] for x in selected})]}
            if item['systems']:details[mode].append(item)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'details.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
