import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';

// The real Worker and SQLite coordinator run in workerd. Only the remote GitHub service is simulated.
export function githubFixture() {
  const releases = new Map(), assets = new Map(); let nextRelease = 1, nextAsset = 1;
  const mock = {dispatches: 0, private: true, assets, privateRedirects: 0};
  const json = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
  const meta = a => ({id: a.id, name: a.name, size: a.data.length, digest: 'sha256:' + createHash('sha256').update(a.data).digest('hex'), browser_download_url: `https://github.com/${a.repo}/releases/download/${a.tag}/${a.name}`});
  const send = (request, data) => {
    let status = 200; const size = data.length, headers = {'Content-Length': String(size)};
    const range = request.headers.get('Range');
    if (range) {
      const m = /^bytes=(\d*)-(\d*)$/.exec(range), begin = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2])), end = m[1] ? Math.min(size - 1, m[2] ? Number(m[2]) : size - 1) : size - 1;
      if (begin >= size || begin > end) return new Response(null, {status: 416, headers: {'Content-Range': `bytes */${size}`}});
      data = data.subarray(begin, end + 1); headers['Content-Range'] = `bytes ${begin}-${end}/${size}`; headers['Content-Length'] = String(data.length); status = 206;
    }
    return new Response(request.method === 'HEAD' ? null : data, {status, headers});
  };
  mock.fetch = async request => {
    const u = new URL(request.url); let m;
    if (u.pathname.endsWith('/dispatches')) { mock.dispatches++; return new Response(null, {status: 204}); }
    if (u.hostname === 'release-assets.githubusercontent.com') {
      assert.equal(request.headers.get('Authorization'), null, 'Never forward credentials to signed asset URLs');
      mock.privateRedirects++; return send(request, assets.get(Number(u.pathname.slice(1))).data);
    }
    if (u.hostname === 'github.com') {
      m = /^\/([^/]+\/[^/]+)\/releases\/download\/([^/]+)\/(.+)$/.exec(u.pathname);
      assert.ok(m); const [, repo, tag, name] = m;
      if (tag.startsWith('album-')) return send(request, readFileSync('output/validation/' + name));
      const asset = [...assets.values()].find(a => a.repo === repo && a.tag === tag && a.name === name);
      assert.ok(asset, 'Saved public asset exists'); assert.equal(repo, 'thebellacross/bellacross-daily'); return send(request, asset.data);
    }
    assert.equal(request.headers.get('Authorization'), 'Bearer test-only-github');
    if ((m = /^\/repos\/([^/]+\/[^/]+)$/.exec(u.pathname))) return json({private: m[1] === 'thebellacross/private-fixture' && mock.private});
    if ((m = /^\/repos\/([^/]+\/[^/]+)\/releases\/assets\/(\d+)$/.exec(u.pathname))) {
      const a = assets.get(Number(m[2])); if (!a || a.repo !== m[1]) return json({}, 404);
      if (request.headers.get('Accept') === 'application/octet-stream') return new Response(null, {status: 302, headers: {Location: 'https://release-assets.githubusercontent.com/' + a.id + '?private-signature=never-expose'}});
      return json(meta(a));
    }
    if ((m = /^\/repos\/([^/]+\/[^/]+)\/releases\/tags\/([^/]+)$/.exec(u.pathname))) {
      const r = releases.get(m[1] + '/' + m[2]); return json(r || {}, r ? 200 : 404);
    }
    if ((m = /^\/repos\/([^/]+\/[^/]+)\/releases$/.exec(u.pathname)) && request.method === 'POST') {
      const b = await request.json(), key = m[1] + '/' + b.tag_name;
      if (releases.has(key)) return json({}, 422);
      const r = {id: nextRelease++, repo: m[1], tag: b.tag_name, draft: b.draft}; releases.set(key, r); return json(r, 201);
    }
    if ((m = /^\/repos\/([^/]+\/[^/]+)\/releases\/(\d+)\/assets$/.exec(u.pathname))) {
      const r = [...releases.values()].find(r => r.id === Number(m[2]) && r.repo === m[1]); assert.ok(r);
      if (request.method === 'POST') {
        const name = u.searchParams.get('name');
        if ([...assets.values()].some(a => a.repo === r.repo && a.tag === r.tag && a.name === name)) return json({}, 422);
        const a = {id: nextAsset++, name, repo: r.repo, tag: r.tag, data: Buffer.from(await request.arrayBuffer())}; assets.set(a.id, a); return json(meta(a), 201);
      }
      const all = [...assets.values()].filter(a => a.repo === r.repo && a.tag === r.tag); const page = Number(u.searchParams.get('page') || 1); return json(all.slice((page - 1) * 100, page * 100).map(meta));
    }
    throw new Error('Unexpected simulated GitHub API request');
  };
  return mock;
}
