from wred import App

app = App()


@app.route('/')
async def hello(request):
    return {'hello': 'world'}


@app.route('/api/health')
async def health(request):
    return {'status': 'ok'}


@app.route('/api/hello/{name}')
async def greet(request, name):
    return {'hello': name, 'language': request.query.get('lang', 'en')}
