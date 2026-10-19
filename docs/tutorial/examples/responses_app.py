import asyncio
from pathlib import Path

from starlette.responses import FileResponse, StreamingResponse
from wred import App

app = App()


@app.route('/download')
async def download(request):
    return FileResponse(
        Path(__file__).with_name('data') / 'notes.json',
        filename='notes.json',
        media_type='application/json',
    )


@app.route('/events')
async def events(request):
    async def messages():
        for number in range(5):
            yield f'data: {number}\n\n'
            await asyncio.sleep(1)

    return StreamingResponse(
        messages(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache'},
    )
