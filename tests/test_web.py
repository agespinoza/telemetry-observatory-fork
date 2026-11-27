import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is required for chart tests')
def test_resource_history_plots_gpu_and_preserves_gaps():
    dashboard = Path(__file__).resolve().parents[1] / 'web' / 'index.html'
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
assert.match(html, /<div class="legend"><span>CPU<\/span><span>GPU<\/span><span>Memory<\/span><\/div>/);
assert.match(html, /aria-label="CPU, GPU and memory percentage history"/);
const start = html.indexOf('function svg(');
const end = html.indexOf('function render(data){', start);
assert.ok(start >= 0 && end > start);
const chart = {
  children: [],
  replaceChildren() { this.children = []; },
  append(child) { this.children.push(child); },
};
const context = {
  document: {
    createElementNS(namespace, tag) {
      return {tag, attrs: {}, setAttribute(key, value) { this.attrs[key] = String(value); }};
    },
  },
  $: () => chart,
  put: () => {},
};
vm.runInNewContext(html.slice(start, end), context);
const sample = gpu => ({cpu_percent: 10, gpu_percent: gpu, memory: {percent: 20}, sampled_at: '2026-01-01T00:00:00Z'});
context.plot([sample(50), sample(40), sample(null), sample(0), sample(10)]);
let gpu = chart.children.filter(child => child.attrs.stroke === '#ffbc74' || child.attrs.fill === '#ffbc74');
assert.equal(gpu.length, 2);
assert.equal(gpu[0].attrs.points, '20,182 185,200');
assert.equal(gpu[1].attrs.points, '515,128 680,110');
assert.equal(gpu[0].attrs['stroke-dasharray'], '7 4');
assert.equal(chart.children.filter(child => child.attrs.stroke === '#5de4da').length, 1);
assert.equal(chart.children.filter(child => child.attrs.stroke === '#6da7ff').length, 1);
context.plot([sample(null), sample(0), {cpu_percent: 10, memory: {percent: 20}}]);
gpu = chart.children.filter(child => child.attrs.stroke === '#ffbc74' || child.attrs.fill === '#ffbc74');
assert.equal(gpu.length, 1);
assert.equal(gpu[0].tag, 'circle');
assert.equal(gpu[0].attrs.cx, '350');
assert.equal(gpu[0].attrs.cy, '200');
context.plot([sample(null), {cpu_percent: 10, memory: {percent: 20}}]);
assert.equal(chart.children.filter(child => child.attrs.stroke === '#ffbc74' || child.attrs.fill === '#ffbc74').length, 0);
"""
    subprocess.run(['node', '-e', script, str(dashboard)], check=True)
