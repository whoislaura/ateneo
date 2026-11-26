// Ejecutar con `npm test` (esbuild de Vite + node:test; sin dependencias nuevas).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, errorMessage } from './api.ts'
import { citationRange, intendedPath } from './helpers.ts'

test('F2: 502/503/504 sin JSON del contrato dan mensaje claro; 503 del backend se respeta', () => {
  for (const status of [502, 503, 504]) assert.match(errorMessage(new ApiError(status, 'http_error', 'x')), /se está iniciando/)
  assert.equal(errorMessage(new ApiError(503, 'ai_unavailable', 'IA no disponible')), 'IA no disponible')
})

test('F4: solo vuelve a una ruta permitida para el rol', () => {
  const student = ['consulta', 'feedback']
  assert.equal(intendedPath('/consulta?x=1', student), '/consulta?x=1')
  assert.equal(intendedPath('/dashboard', student), '/')
  assert.equal(intendedPath(undefined, student), '/')
  assert.equal(intendedPath('/consultaX', student), '/')
})

test('F5: offsets en code points con caracteres fuera del BMP', () => {
  const text = '😀😀 art. 5 del código'
  const quote = 'art. 5'
  assert.deepEqual(citationRange(text, { start: 3, end: 9, quote }), { start: 5, end: 11 })
  // offsets que no cuadran: recurre a indexOf
  assert.deepEqual(citationRange(text, { start: 0, end: 2, quote }), { start: 5, end: 11 })
  assert.equal(citationRange(text, { start: 0, end: 2, quote: 'nada' }), null)
})
