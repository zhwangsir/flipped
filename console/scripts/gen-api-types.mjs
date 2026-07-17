#!/usr/bin/env node
/**
 * M136-B3 — 零依赖 OpenAPI → TypeScript 类型生成器。
 *
 * 从运行中的 flipped 后端拉取 OpenAPI JSON，生成 src/api-types.d.ts：
 *   - 每个 components.schemas 条目 → export interface <Name>
 *   - export interface paths { 路径 → 方法 → { params, requestBody, responses } }
 *
 * 用法：
 *   node scripts/gen-api-types.mjs
 *   FLIPPED_API_URL=http://127.0.0.1:8123 node scripts/gen-api-types.mjs
 *
 * 注意：FastAPI 默认把 OpenAPI 挂在根路径 /openapi.json（不在 /api/v1 前缀下），
 * 脚本会依次尝试 /openapi.json 与 /api/v1/openapi.json。
 */
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = (process.env.FLIPPED_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
// FLIPPED_API_TYPES_OUT 可覆盖输出路径（验收脚本据此做"提交版 vs 实时契约"漂移比对，
// 不污染工作区里的已提交文件）。
const OUT = process.env.FLIPPED_API_TYPES_OUT
  || join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'api-types.d.ts');
const HTTP_METHODS = ['get', 'post', 'put', 'delete', 'patch', 'head', 'options'];

async function fetchSpec() {
  const candidates = ['/openapi.json', '/api/v1/openapi.json'];
  const errors = [];
  for (const path of candidates) {
    try {
      const res = await fetch(`${BASE}${path}`, { signal: AbortSignal.timeout(8000) });
      if (res.ok) return { spec: await res.json(), url: `${BASE}${path}` };
      errors.push(`${path} → HTTP ${res.status}`);
    } catch (e) {
      errors.push(`${path} → ${e.message}`);
    }
  }
  throw new Error(
    `无法从 ${BASE} 获取 OpenAPI JSON（${errors.join('; ')}）。\n` +
    `请先启动后端: PYTHONPATH=src .venv/bin/python -m uvicorn api.main:app --port <port>`,
  );
}

function refName(ref) {
  return String(ref).split('/').pop().replace(/[^A-Za-z0-9_]/g, '_');
}

/** OpenAPI schema → TS 类型字符串。未知/复杂结构回退 unknown（零依赖原则）。 */
function tsType(schema) {
  if (schema == null || typeof schema !== 'object') return 'unknown';
  if (schema.$ref) return refName(schema.$ref);
  if (schema.const !== undefined) return JSON.stringify(schema.const);
  if (Array.isArray(schema.enum)) {
    return schema.enum.map((v) => (v === null ? 'null' : JSON.stringify(v))).join(' | ') || 'unknown';
  }
  for (const combiner of ['anyOf', 'oneOf']) {
    if (Array.isArray(schema[combiner])) {
      const parts = schema[combiner].map(tsType);
      if (schema.nullable) parts.push('null');
      return [...new Set(parts)].join(' | ') || 'unknown';
    }
  }
  if (Array.isArray(schema.allOf) && schema.allOf.length === 1) return tsType(schema.allOf[0]);
  const t = Array.isArray(schema.type) ? schema.type : [schema.type];
  const parts = t.filter(Boolean).map((one) => {
    switch (one) {
      case 'string': return 'string';
      case 'integer': case 'number': return 'number';
      case 'boolean': return 'boolean';
      case 'null': return 'null';
      case 'array': return `${wrap(tsType(schema.items))}[]`;
      case 'object': return objectType(schema);
      default: return 'unknown';
    }
  });
  if (parts.length === 0) return objectType(schema); // 无 type 但有 properties 的情况
  return [...new Set(parts)].join(' | ');
}

function wrap(t) {
  return t.includes(' | ') ? `(${t})` : t;
}

function objectType(schema) {
  if (schema.properties && Object.keys(schema.properties).length > 0) {
    return inlineObject(schema);
  }
  if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
    return `Record<string, ${tsType(schema.additionalProperties)}>`;
  }
  return 'Record<string, unknown>';
}

function inlineObject(schema) {
  const required = new Set(schema.required || []);
  const props = Object.entries(schema.properties).map(([name, prop]) => {
    const opt = required.has(name) ? '' : '?';
    return `${JSON.stringify(name)}${opt}: ${tsType(prop)}`;
  });
  return `{ ${props.join('; ')} }`;
}

function genInterfaces(schemas) {
  const out = [];
  for (const [name, schema] of Object.entries(schemas)) {
    const safe = refName(name);
    if (schema.type === 'object' || schema.properties) {
      const required = new Set(schema.required || []);
      out.push(`export interface ${safe} {`);
      for (const [prop, ps] of Object.entries(schema.properties || {})) {
        const opt = required.has(prop) ? '' : '?';
        const desc = ps.description ? `  /** ${String(ps.description).replace(/\*\//g, '* /')} */\n` : '';
        out.push(`${desc}  ${JSON.stringify(prop)}${opt}: ${tsType(ps)};`);
      }
      out.push('}');
    } else {
      out.push(`export type ${safe} = ${tsType(schema)};`);
    }
    out.push('');
  }
  return out.join('\n');
}

function pickJsonSchema(content) {
  if (!content || typeof content !== 'object') return null;
  const media = content['application/json'] || Object.values(content)[0];
  return media && media.schema ? media.schema : null;
}

function genPaths(paths) {
  const lines = ['export interface paths {'];
  for (const [path, item] of Object.entries(paths)) {
    lines.push(`  ${JSON.stringify(path)}: {`);
    for (const method of HTTP_METHODS) {
      const op = item[method];
      if (!op) continue;
      lines.push(`    ${method}: {`);
      // query / path 参数
      const params = (op.parameters || []).filter((p) => p.in === 'query' || p.in === 'path');
      if (params.length > 0) {
        lines.push('      params: {');
        for (const p of params) {
          const opt = p.required ? '' : '?';
          lines.push(`        ${JSON.stringify(p.name)}${opt}: ${tsType(p.schema || {})};`);
        }
        lines.push('      };');
      } else {
        lines.push('      params?: Record<string, never>;');
      }
      // 请求体
      const bodySchema = op.requestBody ? pickJsonSchema(op.requestBody.content) : null;
      lines.push(`      requestBody: ${bodySchema ? tsType(bodySchema) : 'null'};`);
      // 响应：优先 200，其次首个 2xx
      const responses = op.responses || {};
      const code = responses['200'] ? '200'
        : Object.keys(responses).find((c) => c.startsWith('2'));
      const respSchema = code ? pickJsonSchema(responses[code].content) : null;
      lines.push('      responses: {');
      lines.push(`        ${code || 'default'}: ${respSchema ? tsType(respSchema) : 'unknown'};`);
      lines.push('      };');
      lines.push('    };');
    }
    lines.push('  };');
  }
  lines.push('}');
  return lines.join('\n');
}

const { spec, url } = await fetchSpec();
const banner = `/**
 * GENERATED FILE — 请勿手改。
 * 来源: ${url}
 * 生成: node scripts/gen-api-types.mjs  (M136-B3, 零依赖)
 * 重新生成前需先启动 flipped 后端。
 */

/* eslint-disable */
`;
const body = [
  genInterfaces(spec.components?.schemas || {}),
  genPaths(spec.paths || {}),
  '',
].join('\n');
writeFileSync(OUT, banner + body, 'utf8');
const nSchemas = Object.keys(spec.components?.schemas || {}).length;
const nPaths = Object.keys(spec.paths || {}).length;
console.log(`[gen-api-types] ${url} → ${OUT}`);
console.log(`[gen-api-types] schemas=${nSchemas} paths=${nPaths}`);
