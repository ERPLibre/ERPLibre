#!/usr/bin/env bash

# Get two last .webm file
videos=($(ls -t *.webm | head -n 2))

if [ ${#videos[@]} -ne 2 ]; then
    echo "Error : you need two files .webm in root directory"
    exit 1
fi

timestamp=$(date +"%Y%m%d_%H%M%S")
output_name="output_${timestamp}.webm"

video1="${videos[0]}"
video2="${videos[1]}"

echo "first video ${video1}"
echo "second video ${video2}"

# Obtenez les durées des vidéos
duration1=$(ffmpeg -i "$video1" 2>&1 | grep 'Duration' | cut -d ' ' -f 4 | tr -d ,)
duration2=$(ffmpeg -i "$video2" 2>&1 | grep 'Duration' | cut -d ' ' -f 4 | tr -d ,)
echo "duration 1 : ${duration1}"
echo "duration 2 : ${duration2}"

# Convertir les durées en secondes
duration1_sec=$(echo "$duration1" | awk -F: '{ print ($1 * 3600) + ($2 * 60) + $3 }')
duration2_sec=$(echo "$duration2" | awk -F: '{ print ($1 * 3600) + ($2 * 60) + $3 }')
echo "duration 1 sec : ${duration1_sec}"
echo "duration 2 sec : ${duration2_sec}"

# Déterminer la durée la plus courte
min_duration=$(echo "$duration1_sec $duration2_sec" | awk '{print ($1 < $2) ? $1 : $2}')
echo "Min duration : ${min_duration}"

# Créez la sortie
#output_name="output.mp4"

# Utiliser ffmpeg pour couper et empiler les vidéos
#ffmpeg -i "$video1" -i "$video2" -filter_complex "
#    [0:v]trim=start=0:end=$min_duration,setpts=PTS-STARTPTS[v0];
#    [1:v]trim=start=0:end=$min_duration,setpts=PTS-STARTPTS[v1];
#    [v0][v1]hstack=inputs=2" "$output_name"

#echo "Les vidéos ont été combinées en $output_name"

ffmpeg -i "${videos[0]}" -i "${videos[1]}" -filter_complex "hstack=inputs=2" "${output_name}"
# with normalize size video
#ffmpeg -i "${videos[0]}" -i "${videos[1]}" -filter_complex "[0:v]scale=320:240[v0]; [1:v]scale=320:240[v1]; [v0][v1]hstack=inputs=2" "${output_name}"

echo "${output_name}"
