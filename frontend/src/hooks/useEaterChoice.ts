import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import type { HouseholdMember } from "../types";
import { useHousehold } from "./useServerState";

export interface EaterChoice {
  /** The household's members; empty for someone alone, while households are
   *  off, or in a demo, and then nothing is picked. */
  members: HouseholdMember[];
  /** What the request sends: null means everyone, the server's own default,
   *  so a member who joins mid-session is not silently left out. Only people
   *  still in the household: one who left since they were picked is dropped,
   *  or the request would name someone the server refuses as not a member. */
  eaters: number[] | null;
  pick: (eaters: number[] | null) => void;
  /** You are eating and your own saved profile needs your consent, which the
   *  form's consent box gives (Generate refuses you without it). */
  youNeedConsent: boolean;
}

/** Who a plan or a Cook Now recipe is cooked for, for the form that sends it. */
export function useEaterChoice(): EaterChoice {
  const { userId, isDemo, householdsEnabled } = useAuth();
  const { data: household } = useHousehold(userId, householdsEnabled && !isDemo);
  const [picked, setPicked] = useState<number[] | null>(null);
  const members = household && household.members.length > 1 ? household.members : [];
  const still = picked?.filter((id) => members.some((m) => m.id === id)) ?? null;
  const eaters = still === null || still.length === members.length ? null : still;
  const ticked = members.filter((m) => eaters === null || eaters.includes(m.id));
  return {
    members,
    eaters,
    pick: setPicked,
    youNeedConsent: ticked.some((m) => m.id === userId && m.needs_consent),
  };
}
