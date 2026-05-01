import asyncio
import edge_tts
from pathlib import Path

OUTPUT_DIR = Path("data/test_audio")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DOCTOR_VOICE = "en-US-ChristopherNeural"
PATIENT_VOICE = "en-US-JennyNeural"

DIALOGUE = [
    ("doctor", "Good morning. What brings you in today?"),
    ("patient", "Hi doctor. I've been having a really bad headache for the past three days."),
    ("doctor", "I see. Where exactly does it hurt? Is it on one side or all over?"),
    ("patient", "It's mostly in the front and around my temples. It throbs when I move suddenly."),
    ("doctor", "How would you rate the pain on a scale of one to ten?"),
    ("patient", "About a seven. It's really affecting my work."),
    ("doctor", "Have you noticed any other symptoms? Nausea, sensitivity to light, or vision changes?"),
    ("patient", "Yes, actually. Bright lights make it worse, and I've felt a bit nauseous."),
    ("doctor", "Do you have any history of migraines in your family?"),
    ("patient", "My mother used to get migraines, I think."),
    ("doctor", "Okay. Let me check your blood pressure and do a quick examination."),
    ("doctor", "Your blood pressure is slightly elevated at one forty over ninety. Otherwise, your neurological exam is normal."),
    ("patient", "What do you think is causing this?"),
    ("doctor", "Based on your symptoms and family history, this appears to be a migraine. The elevated blood pressure might also be contributing."),
    ("patient", "What should I do?"),
    ("doctor", "I'm going to prescribe sumatriptan for the acute attacks. I also recommend keeping a headache diary to identify triggers."),
    ("doctor", "Make sure to stay hydrated, get regular sleep, and avoid excessive caffeine. If symptoms worsen or you develop new symptoms, come back immediately."),
    ("patient", "Thank you, doctor. How long should I take the medication?"),
    ("doctor", "Take it only when you have a headache. If you're having more than four migraines a month, we'll discuss preventive options. Let's schedule a follow-up in two weeks."),
    ("patient", "Sounds good. Thank you for your help.")
]

async def generate_audio():
    print("Generating English medical dialogue audio...")
    
    audio_parts = []
    
    for i, (speaker, text) in enumerate(DIALOGUE):
        voice = DOCTOR_VOICE if speaker == "doctor" else PATIENT_VOICE
        communicate = edge_tts.Communicate(text, voice)
        
        part_file = OUTPUT_DIR / f"part_{i}.mp3"
        await communicate.save(str(part_file))
        audio_parts.append(part_file)
        print(f"  Generated part {i+1}/{len(DIALOGUE)}: [{speaker}] {text[:50]}...")
    
    print("\nCombining audio parts...")
    
    from pydub import AudioSegment
    
    combined = AudioSegment.empty()
    for part_file in audio_parts:
        segment = AudioSegment.from_mp3(str(part_file))
        combined += segment
        combined += AudioSegment.silent(duration=500)
    
    output_file = OUTPUT_DIR / "english_dialogue_test.mp3"
    combined.export(str(output_file), format="mp3")
    
    for part_file in audio_parts:
        part_file.unlink()
    
    duration_seconds = len(combined) / 1000
    print(f"\nAudio generated successfully!")
    print(f"Output file: {output_file}")
    print(f"Duration: {duration_seconds:.1f} seconds")
    print(f"Total turns: {len(DIALOGUE)}")

if __name__ == "__main__":
    asyncio.run(generate_audio())
