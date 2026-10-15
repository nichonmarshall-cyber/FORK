"use client";

/**
 * Whether the notebook on screen can be changed. False for the shared demo
 * notebook: its edit controls are hidden rather than shown and refused. The
 * backend refuses every change to it regardless (accounts.auth.require_writable).
 */
import { createContext, useContext } from "react";

export const ReadOnlyContext = createContext(false);

export function useReadOnly(): boolean {
  return useContext(ReadOnlyContext);
}
