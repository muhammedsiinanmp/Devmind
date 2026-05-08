import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn("Supabase credentials not configured");
}

export const supabase = createClient(supabaseUrl || "", supabaseAnonKey || "");

export type Database = {
  public: {
    Tables: {
      review_status_updates: {
        Row: {
          id: number;
          review_id: number;
          status: string;
          summary: string;
          risk_score: number;
          updated_at: string;
        };
        Insert: {
          review_id: number;
          status: string;
          summary?: string;
          risk_score?: number;
          updated_at?: string;
        };
        Update: {
          review_id?: number;
          status?: string;
          summary?: string;
          risk_score?: number;
          updated_at?: string;
        };
      };
    };
  };
};
