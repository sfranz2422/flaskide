/* Every JSON body this page sends to its own server goes as base64.
 *
 * Render puts a firewall in front of the app, and it refuses requests whose
 * body looks like an attack. In a web programming class that is the
 * material: a teacher's notes full of HTML, Flask routes and f-strings were
 * turned away before they reached the app — nothing in its logs — and the
 * editor, handed the firewall's page where it expected JSON, said "Couldn't
 * reach the server." The assignment never saved, and no one line was to
 * blame: each part pasted on its own saved fine. A student's draft can trip
 * it just the same.
 *
 * So the body goes as {"_packed": base64(utf-8 JSON)} and app.py's
 * PackedRequest unwraps it before any route reads it. Done here, by wrapping
 * fetch, rather than at each of the ~50 calls, because a call that was
 * missed would fail exactly as silently as the bug did. Only same-origin
 * requests with a JSON content type and a string body are touched — the
 * Google and Classroom calls, uploads and form posts go as they always have.
 *
 * Load this before any other script on the page: a script that saved a
 * reference to fetch before this ran would go round it.
 */
(function () {
  "use strict";
  if (!window.fetch || window.fetch.packed) return;

  var plain = window.fetch;

  // Keepalive requests (the save as a tab closes) are capped at 64 KB by the
  // browser, and base64 adds a third. Over the cap the browser refuses the
  // request outright, so there, and only there, the plain body is the better
  // bet — it is what was sent before this file existed.
  var KEEPALIVE_LIMIT = 64 * 1024;

  function toBase64(text) {
    var bytes = new TextEncoder().encode(text);
    var out = "";
    // String.fromCharCode over one huge array blows the call stack.
    for (var i = 0; i < bytes.length; i += 0x8000) {
      out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(out);
  }

  function contentType(headers) {
    if (!headers) return "";
    if (typeof Headers !== "undefined" && headers instanceof Headers) {
      return headers.get("Content-Type") || "";
    }
    for (var k in headers) {
      if (k.toLowerCase() === "content-type") return String(headers[k]);
    }
    return "";
  }

  function sameOrigin(input) {
    if (typeof input !== "string") return false;   // a Request: leave it be
    try {
      return new URL(input, window.location.href).origin === window.location.origin;
    } catch (e) {
      return false;
    }
  }

  function pack(body) {
    return JSON.stringify({ _packed: toBase64(body) });
  }

  function packedFetch(input, init) {
    if (init && typeof init.body === "string" && sameOrigin(input)
        && /^application\/json/i.test(contentType(init.headers))) {
      var body = pack(init.body);
      if (!(init.keepalive && body.length > KEEPALIVE_LIMIT
            && init.body.length <= KEEPALIVE_LIMIT)) {
        init = Object.assign({}, init, { body: body });
      }
    }
    return plain.call(this, input, init);
  }
  packedFetch.packed = true;
  window.fetch = packedFetch;

  window.FlaskIDEPack = { pack: pack };
}());
