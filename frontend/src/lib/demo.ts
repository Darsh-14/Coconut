import { createContext, useContext } from 'react'

export const DemoContext = createContext(false)
export const useDemo = () => useContext(DemoContext)
