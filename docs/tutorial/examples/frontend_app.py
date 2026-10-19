from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from wred import App

api = App()


@api.route('/hello')
async def hello(request):
    return {'hello': 'world'}


app = Starlette(routes=[
    Mount('/api', app=api),
    Mount('/', app=StaticFiles(directory=Path(__file__).with_name('frontend'), html=True)),
])
