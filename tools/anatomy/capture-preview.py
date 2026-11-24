import base64
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

import websocket

ROOT = Path(__file__).parent


def capture():
    chrome = os.environ.get('CHROME_PATH') or shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome:
        raise RuntimeError('Chrome not found; set CHROME_PATH')
    output = ROOT/'frames'
    output.mkdir(exist_ok=True)
    ws = None
    with tempfile.TemporaryDirectory(prefix='anatomy-capture-') as profile:
        process = subprocess.Popen([chrome, '--headless', '--no-sandbox', '--disable-gpu',
            '--disable-background-networking', '--remote-allow-origins=*',
            '--remote-debugging-port=0', '--user-data-dir='+profile, 'about:blank'],
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        lines = queue.Queue()

        def consume():
            for line in process.stderr:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic()+20
            address = None
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=min(.2, max(.001, deadline-time.monotonic())))
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError('Chrome exited before DevTools became ready')
                    continue
                if line is None:
                    raise RuntimeError('Chrome stderr closed before DevTools became ready')
                if 'DevTools listening on ' in line:
                    address = line.split('DevTools listening on ')[1].strip()
                    break
            if address is None:
                raise TimeoutError('Chrome DevTools startup exceeded 20 seconds')
            port = address.split(':')[2].split('/')[0]
            with urllib.request.urlopen('http://127.0.0.1:'+port+'/json', timeout=5) as response:
                targets = json.load(response)
            page = next((target for target in targets if target.get('type') == 'page'), None)
            if page is None:
                raise RuntimeError('Chrome returned no page target')
            ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=10)
            sequence = 0

            def call(method, params=None):
                nonlocal sequence
                sequence += 1
                current = sequence
                ws.send(json.dumps({'id': current, 'method': method, 'params': params or {}}))
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    ws.settimeout(min(10, max(.001, deadline-time.monotonic())))
                    result = json.loads(ws.recv())
                    if result.get('id') == current:
                        if 'error' in result:
                            raise RuntimeError(result['error'])
                        return result.get('result', {})
                raise TimeoutError('DevTools command exceeded 15 seconds: '+method)

            call('Page.enable')
            call('Runtime.enable')
            call('Emulation.setDeviceMetricsOverride', {
                'width': 720, 'height': 1280, 'deviceScaleFactor': 1, 'mobile': False})
            call('Page.navigate', {'url': (ROOT/'vertical-preview.html').as_uri()})
            deadline = time.monotonic()+10
            while time.monotonic() < deadline:
                result = call('Runtime.evaluate', {
                    'expression': 'typeof window.renderFrame', 'returnByValue': True})
                if result.get('result', {}).get('value') == 'function':
                    break
                time.sleep(.1)
            else:
                raise TimeoutError('renderFrame did not load within 10 seconds')
            for index in range(192):
                result = call('Runtime.evaluate', {'expression': f'window.renderFrame({index/24})'})
                if 'exceptionDetails' in result:
                    raise RuntimeError(result['exceptionDetails'])
                image = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
                (output/f'{index:04}.png').write_bytes(base64.b64decode(image['data']))
            print('captured 192 fixed-time frames')
        finally:
            if ws is not None:
                ws.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=2)
            process.stderr.close()


if __name__ == '__main__':
    capture()
