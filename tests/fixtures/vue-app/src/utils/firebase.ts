import { initializeApp } from 'firebase/app'
import { getDatabase, ref, set } from 'firebase/database'

const db = getDatabase(initializeApp({ projectId: 'trip-planner' }))

export async function saveTrip(state: unknown) {
  await set(ref(db, 'trip'), state)
}
