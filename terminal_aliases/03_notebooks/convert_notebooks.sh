#!/usr/bin/env bash

# ==========================================================
# Convert notebooks recursively to PDF
# Move PDFs preserving structure
# Merge PDFs recursively per folder
# Delete individual PDFs after merge
# ==========================================================

SOURCE_DIR="$1"

if [ -z "$SOURCE_DIR" ]; then
    echo "Usage:"
    echo "  ./convert_notebooks.sh /path/to/folder"
    exit 1
fi

# Remove trailing slash
SOURCE_DIR="${SOURCE_DIR%/}"

# Output root folder
OUTPUT_DIR="${SOURCE_DIR}_pdfs"

mkdir -p "$OUTPUT_DIR"

echo "=================================================="
echo "STEP 1: Converting notebooks to PDF..."
echo "=================================================="

# --------------------------------------------------
# STEP 1: Convert notebooks in-place
# --------------------------------------------------

find "$SOURCE_DIR" -type f -name "*.ipynb" | while read -r notebook
do
    echo
    echo "Converting:"
    echo "$notebook"

    notebook_dir=$(dirname "$notebook")
    notebook_file=$(basename "$notebook")
    output_name="${notebook_file%.ipynb}"

    (
        cd "$notebook_dir" || exit

        jupyter nbconvert \
            --to pdf \
            "$notebook_file" \
            --output "$output_name" \
            --log-level ERROR
    )

    if [ -f "$notebook_dir/$output_name.pdf" ]; then
        echo "SUCCESS"
    else
        echo "FAILED"
    fi

done

echo
echo "=================================================="
echo "STEP 2: Moving PDFs preserving structure..."
echo "=================================================="

# --------------------------------------------------
# STEP 2: Move PDFs preserving structure
# --------------------------------------------------

find "$SOURCE_DIR" -type f -name "*.pdf" | while read -r pdf
do
    # Relative path
    relative_path="${pdf#$SOURCE_DIR/}"

    # Destination
    destination="$OUTPUT_DIR/$relative_path"

    # Create destination directory
    mkdir -p "$(dirname "$destination")"

    # Replace old PDFs automatically
    mv -f "$pdf" "$destination"

    echo "Moved:"
    echo "$destination"

done

echo
echo "=================================================="
echo "STEP 3: Merging PDFs recursively..."
echo "=================================================="

# --------------------------------------------------
# STEP 3: Merge PDFs inside every folder
# --------------------------------------------------

find "$OUTPUT_DIR" -type d | while read -r dir
do
    # Find PDFs only inside current folder
    mapfile -t pdfs < <(
        find "$dir" -maxdepth 1 -type f -name "*.pdf" \
        ! -name "$(basename "$dir").pdf" \
        | sort
    )

    pdf_count="${#pdfs[@]}"

    # Skip if no PDFs
    if [ "$pdf_count" -eq 0 ]; then
        continue
    fi

    folder_name=$(basename "$dir")

    merged_pdf="$dir/${folder_name}.pdf"

    echo
    echo "Merging PDFs in:"
    echo "$dir"

    # Remove old merged PDF if exists
    rm -f "$merged_pdf"

    # Merge
    pdfunite "${pdfs[@]}" "$merged_pdf"

    # Verify merge success
    if [ -f "$merged_pdf" ]; then
        echo "Merged successfully:"
        echo "$merged_pdf"

        echo "Deleting individual PDFs..."

        # Delete individual PDFs
        for pdf in "${pdfs[@]}"
        do
            rm -f "$pdf"
        done

    else
        echo "Merge FAILED:"
        echo "$dir"
    fi

done

echo
echo "=================================================="
echo "DONE!"
echo "Final merged PDFs available at:"
echo "$OUTPUT_DIR"
echo "=================================================="