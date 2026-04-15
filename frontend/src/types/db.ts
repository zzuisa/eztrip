export interface DbStation {
  id: string
  name: string
  type: string
  latitude?: number
  longitude?: number
  distance?: number
}

export interface DbTrip {
  train_name: string
  origin: string
  destination: string
  departure_time: string
  arrival_time: string
  platform: string
  status: string
}

export interface DbNlqRequest {
  query: string
}

export interface DbNlqResponse {
  success: boolean
  message: string
  parsed?: {
    origin: string
    destination: string
    date: string
    hour: string
    language: string
  }
  data: DbTrip[]
  policy_version?: string
}

