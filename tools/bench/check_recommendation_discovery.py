"""Read-only user DB snapshot; real metadata-only discovery diagnostics."""
import json, logging, os, sqlite3, sys, tempfile, threading, time, hashlib
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))

def main():
    user_db=Path.home()/'.nedotify/nedotify_storage.db'
    with tempfile.TemporaryDirectory(prefix='nedotify-discovery-') as folder:
        scratch=Path(folder);(scratch/'.nedotify').mkdir()
        with sqlite3.connect(user_db.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(scratch/'.nedotify/nedotify_storage.db') as dst:src.backup(dst)
        src.close();dst.close()
        for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA'):os.environ[key]=str(scratch)
        logging.disable(logging.CRITICAL)
        from core.database import DatabaseManager
        from core.settings import SettingsManager
        from services.soundcloud_service import SoundCloudService
        from services.youtube_service import YouTubeService
        from services.recommendation_service import RecommendationService
        from services.deezer_service import DeezerService
        db=DatabaseManager(str(scratch/'.nedotify/nedotify_storage.db'));settings=SettingsManager(db)
        sc=SoundCloudService(settings);yt=YouTubeService(settings);dz=DeezerService(settings)
        rec=RecommendationService(settings,db,sc,yt);p=rec._profile();known={rec._content_key(t) for t in rec._known_tracks(p)}
        seeds=rec._seed_tracks(p,5);artists=rec._get_merged_seed_artists(p,limit=3)
        report={'known_fingerprint':hashlib.sha256(json.dumps(sorted(map(str,known)),ensure_ascii=False).encode()).hexdigest(),'signals':{'known':len(known),'artists':len(p.top_artists)},'seeds':[{'source':t.get('source'),'source_id':t.get('source_id'),'artist':t.get('artist'),'title':t.get('title')} for t in seeds],'artists':artists,'providers':[]}
        graph_seeds, seed_checks = [], []
        related, metadata = sc.get_related_tracks_sync, sc.get_track_metadata
        def record_related(sid, *args, **kwargs):
            graph_seeds.append(str(sid))
            return related(sid, *args, **kwargs)
        def record_metadata(sid):
            result = metadata(sid)
            seed_checks.append({'source_id':str(sid), **{k:result.get(k) for k in ('title','artist','duration')}})
            return result
        sc.get_related_tracks_sync, sc.get_track_metadata = record_related, record_metadata
        event=threading.Event();box={};mix_keys=[]
        def success(mixes):
            rows=[]
            for mix in mixes:
                tracks=mix.get('tracks',[]);keys=[rec._content_key(t) for t in tracks];mix_keys.append(set(keys))
                rows.append({'title':mix.get('title'),'count':len(tracks),'unique':len(set(keys)),
                    'new':sum(key not in known for key in keys),
                    'sources':dict(Counter(t.get('source') for t in tracks)),
                    'recording_ids':[[t.get('source'),str(t.get('source_id'))] for t in tracks],
                    'evidence':dict(Counter(t.get('recommendation_source','known') for t in tracks)),
                    'new_examples':[{k:t.get(k) for k in ('source','source_id','title','artist')} for t in tracks if rec._content_key(t) not in known][:4]})
            box['mixes']=rows;event.set()
        started=time.monotonic();cpu_started=time.process_time()
        rec.get_mixes(max_results=6,callback=success,error_callback=lambda e:(box.update(error=type(e).__name__),event.set()))
        report['mixes_completed']=event.wait(25)
        report['mix_wall_ms']=round((time.monotonic()-started)*1000);report['mix_cpu_ms']=round((time.process_time()-cpu_started)*1000)
        report.update(box)
        report['soundcloud_graph_seeds'] = list(graph_seeds)
        report['soundcloud_seed_checks'] = list(seed_checks)
        report['shared_overlap']=[{'a':i,'b':j,'shared':len(mix_keys[i]&mix_keys[j])} for i in range(len(mix_keys)) for j in range(i+1,len(mix_keys))]
        def measure(name,work):
            started=time.monotonic()
            try:
                items=work();return {'name':name,'ms':round((time.monotonic()-started)*1000),'count':len(items),'new':sum(rec._content_key(t) not in known for t in items),'examples':[{k:t.get(k) for k in ('source','source_id','artist','title')} for t in items[:3]]}
            except Exception as e:return {'name':name,'error':type(e).__name__,'ms':round((time.monotonic()-started)*1000)}
        sc_seed=next((t for t in seeds if t.get('source')=='soundcloud'),{'source_id':'303974832'})
        yt_seed=next((t for t in seeds if t.get('source')=='youtube'),{'source_id':'dQw4w9WgXcQ'})
        report['providers'].append(measure('soundcloud_related',lambda:sc.get_related_tracks_sync(sc_seed['source_id'],20)))
        report['providers'].append(measure('youtube_radio',lambda:yt.get_related_tracks_sync(yt_seed['source_id'],20)))
        for artist in artists[:2]:
            started=time.monotonic()
            try:
                found=dz._get('search/artist',q=artist,limit=1).get('data',[])
                if not found:report['providers'].append({'name':'deezer_artist','artist':artist,'count':0});continue
                aid=dz._id(found[0]['id'])
                report['providers'].append(measure('deezer_radio:'+artist,lambda aid=aid:[dz._track(t) for t in dz._get('artist/'+aid+'/radio',limit=30).get('data',[])]))
                related=dz._get('artist/'+aid+'/related',limit=6).get('data',[])
                report['providers'].append({'name':'deezer_related_artists','artist':artist,'count':len(related),'ms':round((time.monotonic()-started)*1000)})
            except Exception as e:report['providers'].append({'name':'deezer','artist':artist,'error':type(e).__name__})
        from services.recommendation_discovery import RecommendationDiscovery
        def verified_catalogue():
            adapter=RecommendationDiscovery(settings,dz)
            for seed in seeds:
                candidates=adapter.get_candidates([seed],[seed.get('artist') or ''],30)
                if candidates:
                    return candidates
            return []
        report['providers'].append(measure('verified_deezer_discovery',verified_catalogue))
        def catalogue_control():
            seed=dz.get_track('3135556')
            return RecommendationDiscovery(settings,dz).get_candidates([seed],[seed['artist']],30)
        report['providers'].append(measure('verified_deezer_public_positive_control',catalogue_control))
        out=ROOT/'tools/bench/results'/('discovery-after-'+time.strftime('%Y%m%d-%H%M%S')+'.json');out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'artifact':str(out),**report},ensure_ascii=True))
        from services.base_service import BaseMusicService
        BaseMusicService.shutdown_executor()
        rec._candidate_executor.shutdown(wait=True,cancel_futures=True);db.close()

if __name__=='__main__':main()
