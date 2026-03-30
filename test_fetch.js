const http = require('http');

const data = JSON.stringify({
  message: 'Iniciar',
  parecer_id: null,
  pasta_id: null
});

const req = http.request({
  hostname: '127.0.0.1',
  port: 8000,
  path: '/chat/message/',
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(data),
    'X-CSRFToken': 'fake', // CSRF will fail... but wait
  }
}, (res) => {
  let body = '';
  res.on('data', d => body += d);
  res.on('end', () => console.log(res.statusCode, body));
});

req.on('error', console.error);
req.write(data);
req.end();
