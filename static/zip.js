/* FlaskIDE — a minimal ZIP writer.
 *
 * Deliberately no library. A zip is just each file's bytes with a small header
 * in front, then a directory at the end listing where each one starts. Using
 * STORE (no compression) makes it about eighty lines instead of pulling in a
 * deflate implementation — and the payload here is PNGs and short text files,
 * where compression would save very little anyway.
 *
 * Produces a standard archive: macOS Finder, Windows Explorer and `unzip` all
 * open it.
 */

window.FlaskIDEZip = (function () {
  "use strict";

  // ---------------------------------------------------------------- CRC32
  var TABLE = (function () {
    var t = new Uint32Array(256);
    for (var i = 0; i < 256; i++) {
      var c = i;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[i] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) {
      c = TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    }
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  // ------------------------------------------------------------- byte help
  function bytesOf(value) {
    if (typeof value === "string") return new TextEncoder().encode(value);
    if (value instanceof Uint8Array) return value;
    return new Uint8Array(value);
  }

  function u16(n) { return [n & 0xFF, (n >>> 8) & 0xFF]; }
  function u32(n) {
    return [n & 0xFF, (n >>> 8) & 0xFF, (n >>> 16) & 0xFF, (n >>> 24) & 0xFF];
  }

  /* Zip stores the timestamp in the old MS-DOS format: a packed date and time
     with two-second resolution and no timezone. */
  function dosTime(d) {
    var time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    var date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    return { time: time & 0xFFFF, date: date & 0xFFFF };
  }

  // ------------------------------------------------------------------ build
  /* entries: [{ name, data }] where data is a string or Uint8Array.
     A name may contain "/" to make folders inside the archive. */
  function build(entries, when) {
    var stamp = dosTime(when || new Date());
    var chunks = [];       // the file section
    var central = [];      // the directory that follows it
    var offset = 0;

    entries.forEach(function (entry) {
      var nameBytes = new TextEncoder().encode(entry.name);
      var data = bytesOf(entry.data);
      var sum = crc32(data);

      var local = [].concat(
        u32(0x04034b50),        // local file header signature
        u16(20),                // version needed (2.0)
        u16(0x0800),            // flags: names are UTF-8
        u16(0),                 // method 0 = stored
        u16(stamp.time), u16(stamp.date),
        u32(sum),
        u32(data.length),       // compressed size == uncompressed for stored
        u32(data.length),
        u16(nameBytes.length),
        u16(0)                  // no extra field
      );
      var header = new Uint8Array(local);

      chunks.push(header, nameBytes, data);

      central.push({
        nameBytes: nameBytes,
        crc: sum,
        size: data.length,
        offset: offset
      });
      offset += header.length + nameBytes.length + data.length;
    });

    var dirStart = offset;
    var dirBytes = [];
    central.forEach(function (e) {
      var rec = [].concat(
        u32(0x02014b50),        // central directory header signature
        u16(20), u16(20),       // version made by / needed
        u16(0x0800), u16(0),    // flags, method
        u16(stamp.time), u16(stamp.date),
        u32(e.crc), u32(e.size), u32(e.size),
        u16(e.nameBytes.length),
        u16(0), u16(0),         // extra, comment
        u16(0), u16(0),         // disk number, internal attrs
        u32(0),                 // external attrs
        u32(e.offset)
      );
      chunks.push(new Uint8Array(rec), e.nameBytes);
      dirBytes.push(rec.length + e.nameBytes.length);
    });

    var dirSize = dirBytes.reduce(function (a, b) { return a + b; }, 0);
    chunks.push(new Uint8Array([].concat(
      u32(0x06054b50),          // end of central directory
      u16(0), u16(0),           // disk numbers
      u16(central.length), u16(central.length),
      u32(dirSize),
      u32(dirStart),
      u16(0)                    // no archive comment
    )));

    var total = chunks.reduce(function (n, c) { return n + c.length; }, 0);
    var out = new Uint8Array(total);
    var at = 0;
    chunks.forEach(function (c) { out.set(c, at); at += c.length; });
    return out;
  }

  function blob(entries, when) {
    return new Blob([build(entries, when)], { type: "application/zip" });
  }

  function download(filename, entries) {
    var url = URL.createObjectURL(blob(entries));
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  return { build: build, blob: blob, download: download, crc32: crc32 };
})();
