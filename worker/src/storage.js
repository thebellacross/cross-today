// Object keys stay stable across the initial free backend and an optional future R2 migration.
// Audio never enters Durable Object storage: only manifests and GitHub asset identifiers do.
const enc = new TextEncoder();
export class StorageError extends Error {
  constructor(message, status = 503, retryAfter = 0) { super(message); this.publicMessage = message; this.status = status; this.retryAfter = retryAfter; }
}
const sha = async data => [...new Uint8Array(await crypto.subtle.digest('SHA-256', data))].map(x => x.toString(16).padStart(2, '0')).join('');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function reserveWrite(coordinator) {
  const now = Date.now();
  const slot = await coordinator.store.transaction(async txn => {
    const recent = (await txn.get('github-writes') || []).filter(t => t > now - 3600000);
    // Below GitHub's documented secondary limits. Exhaustion pauses writes, never buys capacity.
    if (recent.length >= 440) throw new StorageError('免费存储正在限流，请稍后重试；已发布专辑和原素材仍保留。', 429, Math.ceil((recent[0] + 3600000 - now) / 1000));
    const next = Math.max(now, (recent.at(-1) || 0) + 1250);
    if (next - now > 20000) throw new StorageError('上传队列繁忙，请稍后重试。', 429, 25);
    recent.push(next); await txn.put('github-writes', recent); return next;
  });
  if (slot > now) await pause(slot - now);
}

export class GitHubBucket {
  constructor(coordinator, bucket) { this.c = coordinator; this.env = coordinator.env; this.store = coordinator.store; this.bucket = bucket; }
  key(key) { return `object:${this.bucket}:${key}`; }
  async api(path, {method = 'GET', body, upload = false, missing = false} = {}) {
    if (method !== 'GET') await reserveWrite(this.c);
    const headers = {'Authorization': `Bearer ${this.env.GITHUB_TOKEN}`, 'User-Agent': 'cross-today', 'Accept': 'application/vnd.github+json'};
    if (body !== undefined) headers['Content-Type'] = upload ? 'application/octet-stream' : 'application/json';
    const response = await fetch((upload ? 'https://uploads.github.com' : 'https://api.github.com') + path, {method, headers, body: body === undefined ? undefined : upload ? body : JSON.stringify(body)});
    if (missing && response.status === 404) return null;
    if (!response.ok) {
      const limited = response.status === 429 || (response.status === 403 && (response.headers.has('Retry-After') || response.headers.get('X-RateLimit-Remaining') === '0'));
      const error = new StorageError(limited ? 'GitHub 免费存储暂时限流，请稍后重试。' : '云端文件操作未完成；请检查 GitHub 连接后重试。', limited ? 429 : 503, limited ? Math.max(60, Number(response.headers.get('Retry-After')) || 60) : 0);
      error.upstreamStatus = response.status; throw error;
    }
    return response.status === 204 ? null : response.json();
  }
  async verifyPrivate() {
    const repo = this.env.STORAGE_REPOSITORY;
    if (!repo || !/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(repo) || repo === this.env.GITHUB_REPOSITORY || repo.split('/')[0] !== this.env.GITHUB_REPOSITORY.split('/')[0]) throw new StorageError('私有素材仓库尚未连接。');
    const info = await this.api('/repos/' + repo);
    if (info?.private !== true) throw new StorageError('素材仓库必须保持私有；上传已停止。', 409);
    return repo;
  }
  async location(key) {
    let m;
    if (this.bucket === 'permanent' && (m = /^selected\/([0-9a-f-]{36})\/(track\.(?:wav|mp3)|cover\.png|provenance\.json|credits\.txt)$/.exec(key))) return {repo: this.env.GITHUB_REPOSITORY, tag: 'kept-' + m[1], name: m[2], public: true};
    if (this.bucket === 'permanent' && (m = /^catalog\/(album-(\d{4})-\d{2}-\d{2})\/cover-small\.jpg$/.exec(key))) return {repo: this.env.GITHUB_REPOSITORY, tag: 'catalog-' + m[2], name: m[1] + '-cover-small.jpg', public: true};
    if (this.bucket === 'permanent' && (m = /^exports\/([0-9a-f-]{36})\/(release(?:-\d{2,4})?\.zip)$/.exec(key))) return {repo: this.env.STORAGE_REPOSITORY, tag: 'export-' + m[1], name: m[2], public: false};
    const digest = await sha(enc.encode(this.bucket + '/' + key));
    const shard = digest.slice(0, 1);
    const tag = await this.store.transaction(async txn => {
      const saved = await txn.get('object-slot:' + digest); if (saved) return saved;
      const count = await txn.get('object-shard:' + shard) || 0;
      const tag = `objects-${shard}-${Math.floor(count / 800)}`;
      await txn.put('object-shard:' + shard, count + 1); await txn.put('object-slot:' + digest, tag); return tag;
    });
    return {repo: this.env.STORAGE_REPOSITORY, tag, name: digest, public: false};
  }
  async release(location) {
    if (!location.public) await this.verifyPrivate();
    const key = `object-release:${location.repo}:${location.tag}`;
    let record = await this.store.get(key); if (record) return record;
    record = await this.api(`/repos/${location.repo}/releases/tags/${location.tag}`, {missing: true});
    if (!record) {
      try { record = await this.api(`/repos/${location.repo}/releases`, {method: 'POST', body: {tag_name: location.tag, target_commitish: 'main', name: location.tag, draft: false, make_latest: 'false', body: location.public ? 'Retained output of the CROSS music project. Excluded from daily cleanup.' : 'Private inputs and retained project records. Do not change this repository to public.'}}); }
      catch (e) { if (e.upstreamStatus !== 422) throw e; record = await this.api(`/repos/${location.repo}/releases/tags/${location.tag}`); }
    }
    const saved = {id: record.id, tag: location.tag}; await this.store.put(key, saved); return saved;
  }
  async upload(key, data, partNumber = 0) {
    const bytes = data instanceof ArrayBuffer ? data : data.buffer ? data : enc.encode(data);
    const digest = await sha(bytes), size = bytes.byteLength;
    const location = await this.location(partNumber ? `${key}/part-${partNumber}` : key);
    // Private names contain no filenames/paths. Content suffix makes retries safe.
    const name = location.public || key.startsWith('exports/') ? location.name : location.name + '-' + digest.slice(0, 24);
    const release = await this.release(location);
    let asset;
    try { asset = await this.api(`/repos/${location.repo}/releases/${release.id}/assets?name=${encodeURIComponent(name)}`, {method: 'POST', body: bytes, upload: true}); }
    catch (e) {
      if (e.upstreamStatus !== 422) throw e;
      for (let page = 1; page <= 10 && !asset; page++) {
        const assets = await this.api(`/repos/${location.repo}/releases/${release.id}/assets?per_page=100&page=${page}`);
        asset = assets.find(a => a.name === name); if (assets.length < 100) break;
      }
      if (!asset) throw e;
    }
    if (asset.size !== size || asset.digest !== 'sha256:' + digest) throw new StorageError('云端文件校验不一致；旧文件未被替换。', 409);
    return {id: asset.id, repo: location.repo, tag: location.tag, name, public: location.public, size, sha256: digest};
  }
  async head(key) {
    const obj = await this.store.get(this.key(key));
    return obj ? {...obj, httpEtag: '"' + obj.sha256 + '"'} : null;
  }
  async put(key, data) {
    if (data instanceof ReadableStream) data = await new Response(data).arrayBuffer();
    if (typeof data === 'string') data = enc.encode(data);
    if (data.byteLength > 32 * 1024 * 1024) throw new StorageError('大文件需要分块上传或后台直接保存。', 413);
    const digest = await sha(data), old = await this.head(key);
    if (old?.sha256 === digest) return old;
    const part = await this.upload(key, data);
    const obj = {size: part.size, sha256: part.sha256, parts: [part]};
    await this.store.put(this.key(key), obj); return obj;
  }
  async createMultipartUpload(key) { return {key, uploadId: crypto.randomUUID()}; }
  resumeMultipartUpload(key, uploadId) {
    const prefix = `object-chunk:${this.bucket}:${uploadId}:`;
    return {
      uploadPart: async (partNumber, data) => {
        const partKey = prefix + String(partNumber).padStart(5, '0');
        const digest = await sha(data), old = await this.store.get(partKey);
        if (old && old.sha256 !== digest) throw new StorageError('重试分块与已保存的内容不同，请重新开始上传。', 409);
        const part = old || await this.upload(key, data, partNumber);
        if (!old) await this.store.put(partKey, {...part, partNumber});
        return {partNumber, etag: part.sha256};
      },
      complete: async parts => {
        const saved = [...(await this.store.list({prefix})).values()];
        if (saved.length !== parts.length || saved.some((p, i) => p.partNumber !== i + 1 || p.sha256 !== parts[i].etag)) throw new StorageError('上传分块不完整。', 409);
        const size = saved.reduce((n, p) => n + p.size, 0);
        const obj = {size, sha256: await sha(enc.encode(saved.map(p => p.sha256).join(''))), chunk_prefix: prefix};
        await this.store.put(this.key(key), obj); return obj;
      }
    };
  }
  async register(key, record) {
    const location = await this.location(key);
    if (!location.public) await this.verifyPrivate();
    if (!Number.isSafeInteger(record.id) || !Number.isSafeInteger(record.bytes) || record.bytes <= 0 || record.bytes >= 2 * 1024 ** 3 || !/^[0-9a-f]{64}$/.test(record.sha256)) throw new StorageError('Invalid saved asset.', 400);
    const asset = await this.api(`/repos/${location.repo}/releases/assets/${record.id}`);
    const expected = `https://github.com/${location.repo}/releases/download/${location.tag}/${location.name}`;
    if (asset.name !== location.name || asset.browser_download_url !== expected || asset.size !== record.bytes || asset.digest !== 'sha256:' + record.sha256) throw new StorageError('永久文件校验失败，尚未标记为保存完成。', 409);
    const part = {id: asset.id, ...location, size: asset.size, sha256: record.sha256};
    await this.store.put(this.key(key), {size: asset.size, sha256: record.sha256, parts: [part]});
  }
  async get(key, options = {}) {
    const obj = await this.head(key); if (!obj) return null;
    const parts = obj.parts || [...(await this.store.list({prefix: obj.chunk_prefix})).values()];
    const begin = options.range?.offset || 0, end = Math.min(obj.size, begin + (options.range?.length ?? obj.size));
    let offset = 0; const segments = [];
    for (const p of parts) {
      const from = Math.max(0, begin - offset), to = Math.min(p.size, end - offset);
      if (to > from) segments.push({p, from, to}); offset += p.size;
    }
    if (segments.length > 20) throw new StorageError('大文件请使用分段 Range 请求。', 413);
    let index = 0, reader, remaining = 0, skip = 0;
    const load = async s => {
      const range = `bytes=${s.from}-${s.to - 1}`;
      let r;
      if (s.p.public) r = await fetch(`https://github.com/${s.p.repo}/releases/download/${s.p.tag}/${s.p.name}`, {headers: {Range: range}});
      else {
        r = await fetch(`https://api.github.com/repos/${s.p.repo}/releases/assets/${s.p.id}`, {headers: {Authorization: `Bearer ${this.env.GITHUB_TOKEN}`, Accept: 'application/octet-stream', 'User-Agent': 'cross-today', Range: range}, redirect: 'manual'});
        if ([301, 302, 307, 308].includes(r.status)) {
          const target = new URL(r.headers.get('Location'));
          if (target.protocol !== 'https:' || !['release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(target.hostname)) throw new StorageError('Private asset redirect rejected.');
          // The short-lived private download URL and credential never leave the server.
          r = await fetch(target, {headers: {Range: range}, redirect: 'manual'});
        }
      }
      if (!r.ok || !r.body) throw new StorageError('音频暂时无法读取，请稍后重试。');
      remaining = s.to - s.from; skip = r.status === 206 ? 0 : s.from; reader = r.body.getReader();
    };
    return {...obj, body: new ReadableStream({
      async pull(controller) {
        try {
          while (true) {
            if (!reader) { if (index >= segments.length) { controller.close(); return; } await load(segments[index++]); }
            const {done, value} = await reader.read();
            if (done) { if (remaining) throw new StorageError('音频传输中断，请重试。'); reader = null; continue; }
            let data = value;
            if (skip) { const count = Math.min(skip, data.byteLength); data = data.subarray(count); skip -= count; }
            if (!data.byteLength) continue;
            data = data.subarray(0, remaining); remaining -= data.byteLength;
            if (!remaining) { await reader.cancel(); reader = null; }
            controller.enqueue(data); return;
          }
        } catch (e) { controller.error(e); }
      },
      async cancel() { if (reader) await reader.cancel(); }
    })};
  }
}
