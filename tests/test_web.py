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
      return {
        tag,
        attrs: {},
        listeners: {},
        setAttribute(key, value) { this.attrs[key] = String(value); },
        addEventListener(type, callback) { this.listeners[type] = callback; },
      };
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


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is required for chart tests')
def test_resource_history_hover_tooltip_tracks_series_and_sample():
    dashboard = Path(__file__).resolve().parents[1] / 'web' / 'index.html'
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[1], 'utf8');
assert.match(html, /<div class="chart-wrap" id="chart-wrap">/);
assert.match(html, /id="chart-tooltip" class="chart-tooltip" role="tooltip" hidden/);
const start = html.indexOf('function svg(');
const end = html.indexOf('function render(data){', start);
assert.ok(start >= 0 && end > start);
function element(tag) {
  return {
    tag,
    attrs: {},
    style: {},
    listeners: {},
    children: [],
    hidden: true,
    textContent: '',
    setAttribute(key, value) { this.attrs[key] = String(value); },
    addEventListener(type, callback) { this.listeners[type] = callback; },
  };
}
const chart = element('svg');
chart.replaceChildren = function() { this.children = []; };
chart.append = function(child) { this.children.push(child); };
chart.getBoundingClientRect = () => ({left: 10, top: 20, width: 700, height: 230});
const tooltip = element('div');
const wrapper = {getBoundingClientRect: () => ({left: 10, top: 20, width: 700, height: 230})};
const nodes = {'chart': chart, 'chart-tooltip': tooltip, 'chart-wrap': wrapper};
const context = {
  document: {
    createElementNS(namespace, tag) { return element(tag); },
  },
  $: id => nodes[id],
  put: () => {},
  pct: value => Number(value).toFixed(1) + '%',
};
vm.runInNewContext(html.slice(start, end), context);
const sample = (cpu, gpu, memory, sampled_at) => ({
  cpu_percent: cpu,
  gpu_percent: gpu,
  memory: {percent: memory},
  sampled_at,
});
const data = [
  sample(33, 10, 55, '2026-01-01T00:02:00Z'),
  sample(22, null, 44.4, '2026-01-01T00:01:00Z'),
  sample(11, 40, 33, '2026-01-01T00:00:00Z'),
];
context.plot(data);
const overlays = chart.children.filter(child => child.attrs['data-series']);
const cpu = overlays.find(child => child.attrs['data-series'] === 'CPU');
const gpu = overlays.find(child => child.attrs['data-series'] === 'GPU');
const memory = overlays.find(child => child.attrs['data-series'] === 'Memory');
assert.ok(cpu && gpu && memory);
assert.equal(overlays.filter(child => child.attrs['data-series'] === 'GPU').length, 2);
const pointer = {clientX: 360, clientY: 130};
cpu.listeners.pointermove(pointer);
assert.equal(tooltip.hidden, false);
assert.equal(tooltip.textContent, `CPU · 22.0% · ${new Date(data[1].sampled_at).toLocaleString()}`);
assert.equal(tooltip.style.left, '350px');
assert.equal(tooltip.style.top, '110px');
cpu.listeners.pointerleave();
assert.equal(tooltip.hidden, true);
gpu.listeners.pointermove({clientX: 10, clientY: 130});
assert.equal(tooltip.textContent, `GPU · 40.0% · ${new Date(data[2].sampled_at).toLocaleString()}`);
memory.listeners.pointermove(pointer);
assert.equal(tooltip.textContent, `Memory · 44.4% · ${new Date(data[1].sampled_at).toLocaleString()}`);
memory.listeners.pointerleave();
assert.equal(tooltip.hidden, true);
"""
    subprocess.run(['node', '-e', script, str(dashboard)], check=True)
