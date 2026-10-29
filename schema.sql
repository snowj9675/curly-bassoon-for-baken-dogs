CREATE TABLE IF NOT EXISTS public.gallery_selections (
    image_id uuid PRIMARY KEY REFERENCES public.saved_images(id) ON DELETE CASCADE,
    object_key text NOT NULL,
    title varchar(160) NOT NULL,
    caption text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);
