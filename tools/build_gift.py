"""Build a private order into a persistent, self-contained HTML gift (stdlib only)."""
import argparse
import base64
import html
import json
import mimetypes
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'


def js(value):
    return json.dumps(value, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def content(source, selector, value):
    pattern = r'(<([\w-]+)\b[^>]*\bid="' + re.escape(selector) + r'"[^>]*>).*?(</\2>)'
    result, count = re.subn(pattern, lambda m: m[1] + html.escape(value).replace('\n', '<br>') + m[3], source, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Template field missing: ' + selector)
    return result


def array_replace(source, name, value):
    result, count = re.subn(r'(\b' + name + r'=)\[.*?\](?=;|,notes=)', lambda m: m[1] + js(value), source, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Template array missing: ' + name)
    return result


def build(config_path, output):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    product = config['product']
    if product not in {'birthday', 'memory', 'record', 'campus', 'letters'}:
        raise ValueError('Unknown product; strawberry is not available yet.')
    order = config['order_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', order):
        raise ValueError('order_id must contain letters, digits, _ or - only.')
    source = (SITE / (product + '.html')).read_text(encoding='utf8')
    scripts = {}
    custom_assets = {}

    def material(name, kind):
        path = (config_path.parent / name).resolve()
        if not path.is_relative_to(config_path.parent) or not path.is_file():
            raise ValueError('Material must be a file inside the order folder: ' + name)
        mime = mimetypes.guess_type(path.name)[0] or ''
        if kind == 'image' and mime not in {'image/jpeg', 'image/png', 'image/webp'}:
            raise ValueError('Use JPG, PNG or WebP images.')
        if kind == 'audio' and path.suffix.lower() not in {'.mp3', '.wav', '.m4a', '.ogg'}:
            raise ValueError('Use MP3, WAV, M4A or OGG audio.')
        if path.stat().st_size > (10 if kind == 'image' else 20) * 1024 * 1024:
            raise ValueError('Material exceeds the image/audio size limit.')
        key = 'assets/custom-' + str(len(custom_assets)) + path.suffix.lower()
        custom_assets[key] = path
        return key

    if product == 'birthday':
        for key in ('name', 'messageCN', 'hiddenWish', 'birthday'):
            if not isinstance(config.get(key), str) or not config[key].strip():
                raise ValueError('Missing birthday field: ' + key)
        for key in ('name', 'messageCN', 'messageEN', 'hiddenWish', 'birthday', 'greeting'):
            if key in config:
                source, count = re.subn(r'(\b' + key + r':\s*)"(?:\\.|[^"\\])*"', lambda m: m[1] + js(config[key]), source, count=1)
                if count != 1:
                    raise ValueError('Missing birthday config: ' + key)
        source = source.replace('CONFIG.greeting.split(" ")', 'escapeGiftText(CONFIG.greeting).split(" ")')
        source = source.replace('CONFIG.messageCN.replace(/\\n/g, "<br>")', 'escapeGiftText(CONFIG.messageCN).replace(/\\n/g, "<br>")')
        source = source.replace('    const TAU =', '    const escapeGiftText = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");\n    const TAU =')
    elif product == 'memory':
        entries = config['moments']
        if len(entries) != 5:
            raise ValueError('The scrapbook layout requires exactly 5 moments; ask the customer to complete them.')
        source = content(source, 'memoryNames', config['names'])
        source = content(source, 'memoryQuote', config['quote'])
        stories = []
        for i, entry in enumerate(entries):
            for key in ('caption', 'date', 'text', 'secret'):
                if not isinstance(entry.get(key), str):
                    raise ValueError('Moment is missing: ' + key)
            pattern = r'(<button\b[^>]*data-photo="' + str(i) + r'"[^>]*>)(.*?)(</button>)'
            def photo(m):
                inner = re.sub(r'(<span class="photo-caption">).*?(</span>)', lambda x: x[1] + html.escape(entry['caption']) + x[2], m[2], flags=re.S)
                if entry.get('image'):
                    image = material(entry['image'], 'image')
                    inner = re.sub(r'(<img\b[^>]*src=")[^"]+', lambda x: x[1] + image, inner, count=1)
                opening = re.sub(r'aria-label="[^"]*"', 'aria-label="' + html.escape(entry['caption'], quote=True) + '"', m[1])
                return opening + inner + m[3]
            source = re.sub(pattern, photo, source, count=1, flags=re.S)
            stories.append({key: entry[key] for key in ('date', 'text', 'secret')})
        scripts['assets/memory.js'] = array_replace((SITE / 'assets/memory.js').read_text(encoding='utf8'), 'stories', stories)
    elif product == 'record':
        source = content(source, 'recipient', config['recipient'])
        source = content(source, 'recordMessage', config['message'])
        source = content(source, 'sender', config['sender'] + ' ♡')
        source = re.sub(r'(<p class="gift-date">).*?(</p>)', lambda m: m[1] + html.escape(config['date']) + m[2], source)
        tracks = [{'src': material(config['audio'], 'audio') if config.get('audio') else 'assets/late-breeze.wav', 'title': config['track'], 'subtitle': '送给 ' + config['recipient']}]
        source = content(source, 'trackTitle', config['track'])
        source = content(source, 'trackSubtitle', tracks[0]['subtitle'])
        source = re.sub(r'(<audio\b[^>]*src=")[^"]+', lambda m: m[1] + tracks[0]['src'], source)
        if config.get('cover'):
            cover = material(config['cover'], 'image')
            source = re.sub(r'(<img\b[^>]*id="recordCover"[^>]*src=")[^"]+', lambda m: m[1] + cover, source)
        scripts['assets/record.js'] = array_replace((SITE / 'assets/record.js').read_text(encoding='utf8'), 'tracks', tracks)
    else:
        entries = config['places' if product == 'campus' else 'letters']
        low = 3 if product == 'campus' else 1
        if not low <= len(entries) <= 5:
            raise ValueError(f'{product} requires {low}–5 entries.')
        script = (SITE / ('assets/' + product + '.js')).read_text(encoding='utf8')
        items = []
        for i, entry in enumerate(entries):
            required = ('title', 'date', 'text', 'secret') if product == 'campus' else ('from', 'title', 'body', 'secret')
            if any(not isinstance(entry.get(key), str) for key in required):
                raise ValueError('Missing entry fields: ' + ', '.join(required))
            item = {key: entry[key] for key in required}
            item['image'] = material(entry['image'], 'image') if entry.get('image') else ('memory-' + str(i+1) + '.webp' if product == 'campus' else None)
            items.append(item)
        script = array_replace(script, 'places' if product == 'campus' else 'letters', items)
        script = script.replace('assetMap[p.image]', '(assetMap[p.image] || p.image)').replace('assetMap[l.image]', '(assetMap[l.image] || l.image)')
        data_attr = 'data-place' if product == 'campus' else 'data-letter'
        source = re.sub(r'<button\b[^>]*' + data_attr + r'="(\d+)"[^>]*>.*?</button>', lambda m: m[0] if int(m[1]) < len(items) else '', source, flags=re.S)
        if product == 'campus':
            script = script.replace("' / 05'", "' / '+String(places.length).padStart(2,'0')").replace("' / 5 个地点'", "' / '+places.length+' 个地点'").replace('visited.size<5', 'visited.size<places.length')
            source = source.replace('5个地点', str(len(items)) + '个地点')
            source = re.sub(r'(<span class="tiny-eyebrow">).*?(</span>)', lambda m: m[1] + html.escape(config['years']) + m[2], source, count=1, flags=re.S)
            source = re.sub(r'(<h1>).*?(</h1>)', lambda m: m[1] + html.escape(config['title']) + m[2], source, count=1, flags=re.S)
            source = re.sub(r'(<button\b[^>]*data-place="(\d+)"[^>]*>)(.*?)(</button>)', lambda m: m[1] + re.sub(r'<span>.*?</span>', lambda _: '<span>' + html.escape(items[int(m[2])]['title']) + '</span>', m[3], flags=re.S) + m[4], source, flags=re.S)
        else:
            who = html.escape(config['recipient'])
            source = source.replace('小满', who)
            source = re.sub(r'(<section class="letters-heading">.*?<p>).*?(</p>)', lambda m: m[1] + html.escape(config['intro']).replace('\n','<br>') + m[2], source, count=1, flags=re.S)
            script = script.replace("'给小满的一封信 · 第'", js('给' + config['recipient'] + '的一封信 · 第'))
            script = script.replace('read.size!==6', 'read.size!==letters.length').replace('read.size===6', 'read.size===letters.length').replace('read.size<6', 'read.size<letters.length').replace("' / 6 份心意'", "' / '+letters.length+' 份心意'").replace("' / 6'", "' / '+letters.length").replace('六份心意，都好好收到了。', '大家的心意，都好好收到了。')
            source = source.replace('0 / 6 份心意', '0 / ' + str(len(items)) + ' 份心意')
            source = re.sub(r'(<button\b[^>]*data-letter="(\d+)"[^>]*>)(.*?)(</button>)', lambda m: m[1] + re.sub(r'<small>.*?</small>', lambda _: '<small>来自 ' + html.escape(items[int(m[2])]['from']) + '</small>', re.sub(r'<b>.*?</b>', lambda _: '<b>' + html.escape(items[int(m[2])]['title']) + '</b>', m[3], flags=re.S), flags=re.S) + m[4], source, flags=re.S)
        scripts['assets/' + product + '.js'] = script

    source = re.sub(r'<title>.*?</title>', lambda _: '<title>' + html.escape(config.get('title', config.get('name', config.get('recipient', '专属礼物')))) + '</title>', source, count=1, flags=re.S)
    # Local previews remain interactive; the durable result comes from this builder.
    source = re.sub(r'<a\b[^>]*href="(?:index|contact)\.html[^>]*>.*?</a>', '', source, flags=re.S)
    def embed_style(m):
        css = (SITE / m[1].split('?')[0]).read_text(encoding='utf8')
        css = css.replace("url('Allura-Regular.ttf')", "url('assets/Allura-Regular.ttf')")
        return '<style>' + css + '</style>'
    source = re.sub(r'<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', embed_style, source)
    embedded_scripts = []
    def embed_script(m):
        key = m[1].split('?')[0]
        embedded_scripts.append(scripts.get(key, (SITE / key).read_text(encoding='utf8')))
        return ''
    source = re.sub(r'<script\b[^>]*src="([^"]+)"[^>]*>\s*</script>', embed_script, source)
    source = source.replace('</body>', '<style>#editMemory,#editRecord,#writeLetter{display:none!important}</style>' + ''.join('<script>' + code.replace('</script', '<\\/script') + '</script>' for code in embedded_scripts) + '</body>')
    cache = {}
    def inline_asset(m):
        name = m[0]
        if name not in cache:
            path = custom_assets.get(name, SITE / name)
            if not path.is_file():
                raise ValueError('Missing resource: ' + name)
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            cache[name] = 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode()
        return cache[name]
    source = re.sub(r'assets/[A-Za-z0-9_./-]+\.(?:webp|jpg|jpeg|png|wav|mp3|m4a|ogg|ttf)', inline_asset, source)
    out = Path(output).resolve() / order
    out.mkdir(parents=True, exist_ok=True)
    file = out / '打开礼物.html'
    file.write_text(source, encoding='utf8')
    note = '请下载保存后，用 Chrome、Edge 或 Safari 打开“打开礼物.html”。\n无需安装和联网；音乐需主动点击播放。微信内置浏览器可能限制本地HTML，请选择系统浏览器。\n这份文件包含专属内容，请自行保管，避免公开转发私人照片或文字。\n'
    (out / '打开方式.txt').write_text(note, encoding='utf8')
    archive = out.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('打开礼物.html', '打开方式.txt'):
            z.write(out / name, name)
    print(json.dumps({'order_id': order, 'product': product, 'html': str(file), 'zip': str(archive)}, ensure_ascii=False))
    return file


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', help='Private order JSON, or an examples/*.json file')
    parser.add_argument('--out', default=str(ROOT / 'deliveries'))
    args = parser.parse_args()
    build(args.config, args.out)
