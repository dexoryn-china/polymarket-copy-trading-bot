import { useSyncExternalStore } from 'react'

const TOKEN_KEY = 'copybot.token'

type Listener = () => void
const listeners = new Set<Listener>()

let token: string = readToken()
let authRequired = false

function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

function emit() {
  listeners.forEach((l) => l())
}

function subscribe(listener: Listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getToken(): string {
  return token
}

export function setToken(value: string) {
  token = value.trim()
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable */
  }
  authRequired = false
  emit()
}

export function markAuthRequired() {
  if (authRequired) return
  authRequired = true
  emit()
}

export function dismissAuthPrompt() {
  authRequired = false
  emit()
}

export function useToken(): string {
  return useSyncExternalStore(subscribe, () => token)
}

export function useAuthRequired(): boolean {
  return useSyncExternalStore(subscribe, () => authRequired)
}
