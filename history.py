"""Download Binance 15m SPOT archives in EUR, verify published SHA256."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile
import market


def download(url):
    with urllib.request.urlopen(url,timeout=45) as r: return r.read()


def main():
    p=argparse.ArgumentParser();p.add_argument('--months',nargs='+',required=True,help='YYYY-MM')
    p.add_argument('--symbols',nargs='+',default=['BTCEUR','ETHEUR','SOLEUR'])
    args=p.parse_args();folder=Path('data');folder.mkdir(exist_ok=True)
    aliases={'BTCEUR':'XBTEUR'};manifest=[]
    for symbol in args.symbols:
        if not symbol.isalnum() or not symbol.endswith('EUR'): raise ValueError('EUR symbols only')
        all_bars={}
        for month in args.months:
            import datetime
            datetime.datetime.strptime(month,'%Y-%m')
            name=f'{symbol}-15m-{month}.zip'
            url=f'https://data.binance.vision/data/spot/monthly/klines/{symbol}/15m/{name}'
            payload=download(url);checksum=download(url+'.CHECKSUM').decode().split()[0]
            if hashlib.sha256(payload).hexdigest()!=checksum: raise ValueError('Checksum mismatch')
            with zipfile.ZipFile(io.BytesIO(payload)) as z:
                members=z.infolist()
                if len(members)!=1 or members[0].file_size>20_000_000:raise ValueError('Invalid archive')
                for row in csv.reader(io.StringIO(z.read(members[0]).decode())):
                    if not row or not row[0].isdigit():continue
                    stamp=int(row[0]);stamp=stamp//(1000000 if stamp>10**14 else 1000)
                    all_bars[stamp]=dict(t=stamp,o=float(row[1]),h=float(row[2]),l=float(row[3]),c=float(row[4]),v=float(row[5]))
            manifest.append(dict(symbol=symbol,month=month,url=url,sha256=checksum))
        bars=[all_bars[t] for t in sorted(all_bars)];market.check(bars,900)
        key=aliases.get(symbol,symbol)
        (folder/(key+'.json')).write_text(json.dumps(bars,separators=(',',':')))
    (folder/'provenance.json').write_text(json.dumps(manifest,indent=2))
    print('Saved verified archives in data/. Different venue from Kraken; not a live performance proof.')

if __name__=='__main__':main()
