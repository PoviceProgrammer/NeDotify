"""Live playlist parsing and atomic import into a disposable library."""
import argparse,json,os,re,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',choices=('youtube','soundcloud','deezer'),required=True)
    parser.add_argument('--target')
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args()
    if not args.child:
        with tempfile.TemporaryDirectory(prefix='nedotify-import-check-') as folder:
            env=dict(os.environ)
            for key in ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA'):env[key]=folder
            command=[sys.executable,__file__,'--provider',args.provider,'--child']
            if args.target:command+=['--target',args.target]
            try:
                result=subprocess.run(command,env=env,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=75,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                print(result.stdout[-3000:].strip())
                if not result.stdout.strip():print(json.dumps({'provider':args.provider,'ok':False,'error':'Child process failed'}))
                return result.returncode
            except subprocess.TimeoutExpired:
                print(json.dumps({'provider':args.provider,'ok':False,'error':'75-second deadline'}));return 1
    sys.path.insert(0,str(ROOT))
    from services.playlist_import_service import PlaylistImportService
    from core.database import DatabaseManager
    start=time.monotonic()
    db=None
    try:
        target=args.target
        if not target and args.provider=='youtube':
            from services.youtube_service import YouTubeService
            hits=YouTubeService()._ytmusic.search('Queen',filter='playlists',limit=5)
            if not hits:raise ValueError('YouTube Music returned no playlists for the live probe')
            target='https://www.youtube.com/playlist?list='+hits[0]['browseId'].removeprefix('VL')
        elif not target and args.provider=='deezer':
            from services.deezer_service import DeezerService
            hits=DeezerService()._get('search/playlist',q='classical',limit=1)
            target='https://www.deezer.com/playlist/'+str(hits['data'][0]['id'])
        if not target:raise ValueError('A public playlist target is required')
        resolved=PlaylistImportService().resolve(target)
        db=DatabaseManager(str(Path(os.environ['USERPROFILE'])/'import-test.db'))
        baseline=db.create_playlist('Existing library')
        pid,count=db.import_playlist_atomic(resolved['name'],'live test',resolved['tracks'])
        stored=db.get_playlist_tracks(pid)
        assert stored and count==len(stored),'Imported count is inconsistent'
        expected=list(dict.fromkeys((t['title'],t['artist']) for t in resolved['tracks']))
        actual=[(t['title'],t['artist']) for t in stored]
        assert actual==expected,f'Track order or metadata mismatch: parsed={len(expected)}, stored={len(actual)}'
        same,again=db.import_playlist_atomic(resolved['name'],'repeat',resolved['tracks'])
        assert same==pid and again==0,'Repeated import changed the collection'
        assert any(p['id']==baseline for p in db.get_playlists()),'Existing playlist was lost'
        print(json.dumps({'provider':args.provider,'ok':True,'tracks':len(stored),'order_verified':True,'repeat_verified':True,'seconds':round(time.monotonic()-start,2)}));return 0
    except Exception as exc:
        print(json.dumps({'provider':args.provider,'ok':False,'seconds':round(time.monotonic()-start,2),'error':re.sub(r'https?://\S+','<url>',str(exc))[:350]},ensure_ascii=True));return 1
    finally:
        if db:db.close()

if __name__=='__main__':raise SystemExit(main())
