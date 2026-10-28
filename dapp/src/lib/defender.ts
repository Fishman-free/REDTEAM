import { readStorage, writeStorage } from "./hooks";

export interface DefenderRegistration {
  wallet: string;
  version?: string;
  digest?: string;
  contestId?: string;
  registeredAt: number;
}

export function defenderStorageKey(address?: string | null): string {
  return `rtm.defender.registration.v1:${(address ?? "guest").toLowerCase()}`;
}

export function readDefenderRegistration(
  address?: string | null,
): DefenderRegistration | null {
  if (!address) return null;
  return readStorage<DefenderRegistration | null>(defenderStorageKey(address), null);
}

export function writeDefenderRegistration(
  address: string,
  registration: DefenderRegistration,
): void {
  writeStorage(defenderStorageKey(address), registration);
}

export function clearDefenderRegistration(address: string): void {
  writeStorage(defenderStorageKey(address), null);
}
